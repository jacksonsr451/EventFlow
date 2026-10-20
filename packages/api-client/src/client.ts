import {
  ApiProblem,
  isProblemPayload,
  statusLabel,
  type ProblemPayload,
} from "./problem";

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export type QueryPrimitive = string | number | boolean;
export type QueryValue =
  | QueryPrimitive
  | null
  | undefined
  | ReadonlyArray<QueryPrimitive>;

export interface RequestOptions {
  method?: HttpMethod;
  query?: Record<string, QueryValue>;
  body?: unknown;
  signal?: AbortSignal;
  headers?: Record<string, string>;
  idempotencyKey?: string;
  ifMatch?: string;
  correlationId?: string;
  suppressUnauthorizedEvent?: boolean;
  keepalive?: boolean;
}

export interface ResponseMeta {
  status: number;
  etag: string | undefined;
  correlationId: string | undefined;
}

export interface RequestResult<T> {
  data: T;
  meta: ResponseMeta;
}

export interface ApiClientOptions {
  baseUrl?: string;
  fetchImpl?: typeof fetch;
  generateCorrelationId?: () => string;
  getCsrfToken?: () => string | null;
  onUnauthorized?: () => void;
}

const UNSAFE_METHODS = new Set<HttpMethod>(["POST", "PUT", "PATCH", "DELETE"]);

function randomId(): string {
  const cryptoApi = globalThis.crypto;
  if (cryptoApi && typeof cryptoApi.randomUUID === "function") {
    return cryptoApi.randomUUID();
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (char) => {
    const value = Math.floor(Math.random() * 16);
    const digit = char === "x" ? value : (value & 0x3) | 0x8;
    return digit.toString(16);
  });
}

function parseRetryAfter(value: string | null): number | undefined {
  if (!value) return undefined;
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) return seconds;
  const date = Date.parse(value);
  if (!Number.isFinite(date)) return undefined;
  return Math.max(0, Math.ceil((date - Date.now()) / 1000));
}

function appendQuery(url: URL, query: Record<string, QueryValue>): void {
  for (const [key, rawValue] of Object.entries(query)) {
    if (rawValue === undefined || rawValue === null) continue;
    const values = Array.isArray(rawValue) ? rawValue : [rawValue];
    for (const value of values) {
      url.searchParams.append(key, String(value));
    }
  }
}

async function parseBody(response: Response): Promise<unknown> {
  if (response.status === 204) return undefined;
  const text = await response.text();
  if (!text) return undefined;
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("json") || text.trim().startsWith("{")) {
    try {
      return JSON.parse(text) as unknown;
    } catch {
      return undefined;
    }
  }
  return text;
}

export class ApiClient {
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;
  private readonly generateCorrelationId: () => string;
  private csrfProvider: (() => string | null) | undefined;
  private unauthorizedHandler: (() => void) | undefined;

  constructor(options: ApiClientOptions = {}) {
    this.baseUrl = (options.baseUrl ?? "").replace(/\/$/, "");
    this.fetchImpl =
      options.fetchImpl ??
      ((input: RequestInfo | URL, init?: RequestInit) =>
        globalThis.fetch(input, init));
    this.generateCorrelationId = options.generateCorrelationId ?? randomId;
    this.csrfProvider = options.getCsrfToken;
    this.unauthorizedHandler = options.onUnauthorized;
  }

  setCsrfTokenProvider(provider: (() => string | null) | undefined): void {
    this.csrfProvider = provider;
  }

  setUnauthorizedHandler(handler: (() => void) | undefined): void {
    this.unauthorizedHandler = handler;
  }

  async request<T>(
    path: string,
    options: RequestOptions = {},
  ): Promise<RequestResult<T>> {
    const method = options.method ?? "GET";
    const target = new URL(
      `${this.baseUrl}${path}`,
      this.baseUrl || globalThis.location?.origin || "http://localhost",
    );
    if (!this.baseUrl) {
      target.protocol = globalThis.location?.protocol ?? "http:";
      target.host = globalThis.location?.host ?? "localhost";
    }
    appendQuery(target, options.query ?? {});

    const correlationId = options.correlationId ?? this.generateCorrelationId();
    const headers = new Headers(options.headers);
    headers.set("Accept", "application/json, application/problem+json");
    headers.set("X-Correlation-ID", correlationId);
    if (options.ifMatch) headers.set("If-Match", options.ifMatch);
    if (options.idempotencyKey) {
      headers.set("Idempotency-Key", options.idempotencyKey);
    }

    let body: BodyInit | undefined;
    if (options.body !== undefined) {
      if (
        typeof FormData !== "undefined" &&
        options.body instanceof FormData
      ) {
        body = options.body;
      } else {
        body = JSON.stringify(options.body);
        headers.set("Content-Type", "application/json");
      }
    }

    if (UNSAFE_METHODS.has(method)) {
      const csrfToken = this.csrfProvider?.() ?? null;
      if (csrfToken) headers.set("X-CSRF-Token", csrfToken);
    }

    let response: Response;
    try {
      response = await this.fetchImpl(target.toString(), {
        method,
        headers,
        body,
        signal: options.signal,
        credentials: "include",
        keepalive: options.keepalive,
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        throw error;
      }
      throw new ApiProblem(0, {
        title: statusLabel(0),
        detail: "Check your connection and try again.",
      });
    }

    const responseCorrelationId =
      response.headers.get("x-correlation-id") ?? correlationId;
    const payload = await parseBody(response);

    if (!response.ok) {
      const problem = isProblemPayload(payload)
        ? (payload as ProblemPayload)
        : {};
      const failure = new ApiProblem(response.status, problem, {
        correlationId: responseCorrelationId,
        retryAfterSeconds: parseRetryAfter(
          response.headers.get("retry-after"),
        ),
        fallbackTitle: statusLabel(response.status),
      });
      if (
        failure.isUnauthorized &&
        !options.suppressUnauthorizedEvent
      ) {
        this.unauthorizedHandler?.();
      }
      throw failure;
    }

    return {
      data: payload as T,
      meta: {
        status: response.status,
        etag: response.headers.get("etag") ?? undefined,
        correlationId: responseCorrelationId,
      },
    };
  }

  async requestData<T>(
    path: string,
    options: RequestOptions = {},
  ): Promise<T> {
    return (await this.request<T>(path, options)).data;
  }
}

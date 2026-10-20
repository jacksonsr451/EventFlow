export interface FieldProblem {
  field: string;
  message: string;
  [key: string]: unknown;
}

export interface ProblemPayload {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  instance?: string;
  code?: string;
  correlation_id?: string;
  request_id?: string;
  errors?: FieldProblem[];
}

const SAFE_MESSAGE = "The request could not be completed.";

export class ApiProblem extends Error {
  readonly status: number;
  readonly code: string | undefined;
  readonly title: string;
  readonly detail: string;
  readonly type: string | undefined;
  readonly instance: string | undefined;
  readonly correlationId: string | undefined;
  readonly requestId: string | undefined;
  readonly fieldErrors: FieldProblem[];
  readonly retryAfterSeconds: number | undefined;

  constructor(
    status: number,
    payload: ProblemPayload = {},
    options: {
      correlationId?: string;
      retryAfterSeconds?: number;
      fallbackTitle?: string;
    } = {},
  ) {
    const detail = payload.detail?.trim() || payload.title?.trim() || SAFE_MESSAGE;
    super(detail);
    this.name = "ApiProblem";
    this.status = payload.status ?? status;
    this.code = payload.code;
    this.title = payload.title?.trim() || options.fallbackTitle || "Request failed";
    this.detail = detail;
    this.type = payload.type;
    this.instance = payload.instance;
    this.correlationId =
      payload.correlation_id ?? options.correlationId ?? undefined;
    this.requestId = payload.request_id;
    this.fieldErrors = Array.isArray(payload.errors) ? payload.errors : [];
    this.retryAfterSeconds = options.retryAfterSeconds;
    Object.setPrototypeOf(this, ApiProblem.prototype);
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }

  get isForbidden(): boolean {
    return this.status === 403;
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }

  get isConflict(): boolean {
    return this.status === 409 || this.status === 412;
  }

  get isRetryable(): boolean {
    return (
      this.status === 0 ||
      this.status === 408 ||
      this.status === 425 ||
      this.status === 429 ||
      this.status >= 500
    );
  }
}

export function isProblem(value: unknown): value is ApiProblem {
  return value instanceof ApiProblem;
}

export function isProblemPayload(value: unknown): value is ProblemPayload {
  return typeof value === "object" && value !== null;
}

export function statusLabel(status: number): string {
  switch (status) {
    case 400:
      return "Invalid request";
    case 401:
      return "Sign-in required";
    case 403:
      return "Permission denied";
    case 404:
      return "Not found";
    case 409:
      return "Conflict";
    case 412:
      return "Data is out of date";
    case 422:
      return "Validation failed";
    case 429:
      return "Too many requests";
    case 0:
      return "Cannot reach EventFlow";
    default:
      return status >= 500 ? "EventFlow is unavailable" : "Request failed";
  }
}

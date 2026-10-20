import { describe, expect, it, vi } from "vitest";
import {
  ApiClient,
  ApiProblem,
  createWorkManagementApi,
  queryKeys,
} from "../src";

function jsonResponse(
  body: unknown,
  status = 200,
  headers: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

describe("ApiClient", () => {
  it("serializes queries, body, correlation and CSRF headers", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse({ ok: true }, 201, { etag: '"v1"' }),
    );
    const client = new ApiClient({
      baseUrl: "https://api.example.test",
      fetchImpl: fetchMock,
      getCsrfToken: () => "csrf-token",
      generateCorrelationId: () => "correlation-id",
    });

    const result = await client.request<{ ok: boolean }>("/v1/example", {
      method: "POST",
      query: { limit: 20, empty: undefined, tag: ["a", "b"] },
      body: { title: "Example" },
      idempotencyKey: "idem-key-123",
      ifMatch: '"etag"',
    });

    expect(result.data).toEqual({ ok: true });
    expect(result.meta).toEqual({
      status: 201,
      etag: '"v1"',
      correlationId: "correlation-id",
    });
    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(String(url)).toBe(
      "https://api.example.test/v1/example?limit=20&tag=a&tag=b",
    );
    const headers = new Headers(init?.headers);
    expect(headers.get("x-csrf-token")).toBe("csrf-token");
    expect(headers.get("x-correlation-id")).toBe("correlation-id");
    expect(headers.get("idempotency-key")).toBe("idem-key-123");
    expect(headers.get("if-match")).toBe('"etag"');
    expect(init?.credentials).toBe("include");
    expect(init?.body).toBe(JSON.stringify({ title: "Example" }));
  });

  it("does not send CSRF on safe requests", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse([]));
    const client = new ApiClient({
      baseUrl: "https://api.example.test",
      fetchImpl: fetchMock,
      getCsrfToken: () => "csrf-token",
    });

    await client.request("/v1/workspaces");

    const [, init] = fetchMock.mock.calls[0] ?? [];
    expect(new Headers(init?.headers).get("x-csrf-token")).toBeNull();
  });

  it("maps problem details and notifies on 401", async () => {
    const onUnauthorized = vi.fn();
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse(
        {
          title: "Unauthorized",
          status: 401,
          detail: "Sign in again.",
          code: "UNAUTHORIZED",
          correlation_id: "corr-401",
          errors: [{ field: "session", message: "Expired" }],
        },
        401,
      ),
    );
    const client = new ApiClient({
      baseUrl: "https://api.example.test",
      fetchImpl: fetchMock,
      onUnauthorized,
    });

    await expect(client.request("/v1/workspaces")).rejects.toMatchObject({
      name: "ApiProblem",
      status: 401,
      code: "UNAUTHORIZED",
      correlationId: "corr-401",
      fieldErrors: [{ field: "session", message: "Expired" }],
    });
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });

  it("suppresses unauthorized events for session initialization", async () => {
    const onUnauthorized = vi.fn();
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(jsonResponse({ detail: "No session" }, 401));
    const client = new ApiClient({
      baseUrl: "https://api.example.test",
      fetchImpl: fetchMock,
      onUnauthorized,
    });

    await expect(
      client.request("/v1/auth/session", {
        suppressUnauthorizedEvent: true,
      }),
    ).rejects.toBeInstanceOf(ApiProblem);
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it("turns network failures into a retryable problem", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockRejectedValue(new TypeError("network down"));
    const client = new ApiClient({
      baseUrl: "https://api.example.test",
      fetchImpl: fetchMock,
    });

    const failure = await client
      .request("/v1/workspaces")
      .catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(ApiProblem);
    expect(failure).toMatchObject({ status: 0, isRetryable: true });
  });

  it("rethrows aborts without converting them to API problems", async () => {
    const abort = new DOMException("Aborted", "AbortError");
    const fetchMock = vi.fn<typeof fetch>().mockRejectedValue(abort);
    const client = new ApiClient({
      baseUrl: "https://api.example.test",
      fetchImpl: fetchMock,
    });

    await expect(client.request("/v1/workspaces")).rejects.toBe(abort);
  });

  it("handles empty 204 responses", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(null, { status: 204 }));
    const client = new ApiClient({
      baseUrl: "https://api.example.test",
      fetchImpl: fetchMock,
    });

    await expect(client.request("/v1/auth/logout", { method: "POST" })).resolves
      .toMatchObject({ data: undefined, meta: { status: 204 } });
  });
});

describe("work management endpoints and query keys", () => {
  it("builds workspace-scoped URLs and filters", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse({ items: [], page_info: { has_more: false, next_cursor: null } }),
    );
    const client = new ApiClient({
      baseUrl: "https://api.example.test",
      fetchImpl: fetchMock,
    });
    const api = createWorkManagementApi(client);

    await api.listConsultations("workspace-1", {
      status: "open",
      priority: "high",
      limit: 25,
      cursor: "cursor-1",
    });

    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      "https://api.example.test/v1/workspaces/workspace-1/consultations?status=open&priority=high&limit=25&cursor=cursor-1",
    );
  });

  it("keeps query keys scoped by workspace and project", () => {
    expect(queryKeys.consultations.list("workspace-a", { status: "open" })).not
      .toEqual(queryKeys.consultations.list("workspace-b", { status: "open" }));
    expect(queryKeys.boards.list("workspace-a", "project-a")).not.toEqual(
      queryKeys.boards.list("workspace-a", "project-b"),
    );
    expect(queryKeys.triage.templates("workspace-a", "project-a")).not.toEqual(
      queryKeys.triage.templates("workspace-b", "project-a"),
    );
  });
});

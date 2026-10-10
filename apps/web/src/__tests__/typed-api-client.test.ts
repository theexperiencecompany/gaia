import { ApiError } from "@shared/api";
import type {
  AuthenticatedUserResponse,
  Body_user_update_holo_card_colors,
  TodoResponse,
  TodoUpdateRequest,
} from "@shared/api/generated";
import { beforeEach, describe, expect, expectTypeOf, it, vi } from "vitest";

const request = vi.fn();

vi.mock("@/lib/api/client", () => ({
  apiauth: { request: (...args: unknown[]) => request(...args) },
  apiOrigin: "http://localhost:8000",
}));
vi.mock("@/lib/toast", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));
vi.mock("@/lib/analytics", () => ({
  ANALYTICS_EVENTS: { API_REQUEST_FAILED: "api:request_failed" },
  trackEvent: vi.fn(),
}));

import { type ApiBody, type ApiResponse, api } from "@/lib/api/typed";

/** The URL the transport was actually asked for, for the nth call. */
const requestedUrl = (nth: number): unknown =>
  (request.mock.calls[nth]?.[0] as { url?: unknown } | undefined)?.url;

/** A transport rejection shaped like the one axios raises for a non-2xx. */
const httpFailure = (status: number, data: unknown) =>
  Object.assign(new Error(`Request failed with status code ${status}`), {
    isAxiosError: true,
    response: {
      status,
      data,
      headers: { "content-type": "application/json" },
    },
  });

describe("path-typed api client", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    request.mockResolvedValue({ status: 200, data: { ok: true }, headers: {} });
  });

  it("fills path parameters and repeats a list query key the way FastAPI reads it", async () => {
    await api.get("/api/v1/calendar/events", {
      query: { max_results: 2, selected_calendars: ["a b", "c"] },
    });
    await api.get("/api/v1/todos/{todo_id}", { path: { todo_id: "t/1" } });

    expect(requestedUrl(0)).toBe(
      "http://localhost:8000/api/v1/calendar/events" +
        "?max_results=2&selected_calendars=a%20b&selected_calendars=c",
    );
    expect(requestedUrl(1)).toBe("http://localhost:8000/api/v1/todos/t%2F1");
  });

  it("sends the body and keeps the toast options", async () => {
    await api.put("/api/v1/todos/{todo_id}", {
      path: { todo_id: "t1" },
      body: { title: "Renamed" },
      silent: true,
    });

    expect(request).toHaveBeenCalledWith(
      expect.objectContaining({
        method: "PUT",
        url: "http://localhost:8000/api/v1/todos/t1",
        data: JSON.stringify({ title: "Renamed" }),
      }),
    );
  });

  it("types the response, the body and the parameters from the schema", () => {
    // openapi-fetch strips its write-only markers with a mapped type, so the
    // response is equivalent to the schema's model rather than identical to it.
    expectTypeOf<
      ApiResponse<"get", "/api/v1/user/me">
    >().toExtend<AuthenticatedUserResponse>();
    expectTypeOf<AuthenticatedUserResponse>().toExtend<
      ApiResponse<"get", "/api/v1/user/me">
    >();
    expectTypeOf<
      ApiResponse<"put", "/api/v1/todos/{todo_id}">
    >().toExtend<TodoResponse>();
    expectTypeOf<
      ApiResponse<"delete", "/api/v1/todos/{todo_id}">
    >().toEqualTypeOf<undefined>();
    expectTypeOf<
      ApiBody<"put", "/api/v1/todos/{todo_id}">
    >().toEqualTypeOf<TodoUpdateRequest>();
    // Never called: these exist for the compiler, which must reject each one.
    const rejected = () => {
      // @ts-expect-error -- a path the API does not serve
      api.get("/api/v1/nope");
      // @ts-expect-error -- the path parameter is mandatory
      api.get("/api/v1/todos/{todo_id}");
      // @ts-expect-error -- a body the route does not declare
      api.get("/api/v1/user/me", { body: {} });
      // @ts-expect-error -- the body is mandatory
      api.post("/api/v1/todos", { silent: true });
    };
    expect(rejected).toBeTypeOf("function");
  });
});

describe("path-typed api client — schema contract", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    request.mockResolvedValue({ status: 200, data: { ok: true }, headers: {} });
  });

  it("requests a path outside /api/v1 at its own URL", async () => {
    await api.get("/health");

    expect(requestedUrl(0)).toBe("http://localhost:8000/health");
  });

  it("puts a required query parameter on the URL", async () => {
    await api.get("/api/v1/search", { query: { query: "invoice" } });

    expect(requestedUrl(0)).toBe(
      "http://localhost:8000/api/v1/search?query=invoice",
    );
  });

  it("resolves a 204 to undefined, not the transport's empty body", async () => {
    request.mockResolvedValue({ status: 204, data: "", headers: {} });

    await expect(
      api.delete("/api/v1/todos/{todo_id}", { path: { todo_id: "t1" } }),
    ).resolves.toBeUndefined();
  });

  it.each([402, 422, 500])(
    "throws an ApiError carrying the %i envelope",
    async (status) => {
      request.mockRejectedValue(
        httpFailure(status, {
          message: "Subscribe to continue",
          code: "subscription_required",
          why: "This endpoint is gated",
          fix: "Upgrade your plan",
        }),
      );

      const error = await api
        .get("/api/v1/user/me", { silent: true })
        .catch((thrown: unknown) => thrown);

      expect(error).toBeInstanceOf(ApiError);
      const apiError = error as ApiError;
      expect(apiError.status).toBe(status);
      expect(apiError.envelope?.code).toBe("subscription_required");
      expect(apiError.envelope?.message).toBe("Subscribe to continue");
      expect(apiError.envelope?.fix).toBe("Upgrade your plan");
    },
  );

  it("types a required query and a form body from the schema", () => {
    expectTypeOf<
      ApiBody<"patch", "/api/v1/user/holo-card/colors">
    >().toEqualTypeOf<Body_user_update_holo_card_colors>();
    // Never called: these exist for the compiler, which must reject each one.
    const rejected = () => {
      // @ts-expect-error -- the route declares `query.query` as required
      api.get("/api/v1/search");
      // @ts-expect-error -- the required query is still missing
      api.get("/api/v1/search", { silent: true });
    };
    expect(rejected).toBeTypeOf("function");
  });
});

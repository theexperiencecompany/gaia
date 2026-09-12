import type { Schema } from "@shared/api/generated";
import { beforeEach, describe, expect, expectTypeOf, it, vi } from "vitest";

const request = vi.fn();

vi.mock("@/lib/api/client", () => ({
  apiauth: { request: (...args: unknown[]) => request(...args) },
}));
vi.mock("@/lib/toast", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));
vi.mock("@/lib/analytics", () => ({
  ANALYTICS_EVENTS: { API_REQUEST_FAILED: "api:request_failed" },
  trackEvent: vi.fn(),
}));

import { type ApiBody, type ApiResponse, api } from "@/lib/api/typed";

describe("path-typed api client", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    request.mockResolvedValue({ data: { ok: true } });
  });

  it("fills path parameters, trims the /api/v1 prefix the base URL carries, and forwards the query", async () => {
    await api.get("/api/v1/todos", {
      query: { page: 2, labels: ["a b", "c"] },
    });
    await api.get("/api/v1/todos/{todo_id}", { path: { todo_id: "t/1" } });

    expect(request).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({
        method: "GET",
        url: "/todos",
        params: { page: 2, labels: ["a b", "c"] },
        paramsSerializer: { indexes: null },
      }),
    );
    expect(request).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ method: "GET", url: "/todos/t%2F1" }),
    );
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
        url: "/todos/t1",
        data: { title: "Renamed" },
      }),
    );
  });

  it("types the response, the body and the parameters from the schema", () => {
    expectTypeOf<ApiResponse<"get", "/api/v1/user/me">>().toEqualTypeOf<
      Schema<"AuthenticatedUserResponse">
    >();
    expectTypeOf<ApiResponse<"put", "/api/v1/todos/{todo_id}">>().toEqualTypeOf<
      Schema<"TodoResponse">
    >();
    expectTypeOf<
      ApiResponse<"delete", "/api/v1/todos/{todo_id}">
    >().toEqualTypeOf<undefined>();
    expectTypeOf<ApiBody<"put", "/api/v1/todos/{todo_id}">>().toEqualTypeOf<
      Schema<"TodoUpdateRequest">
    >();
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

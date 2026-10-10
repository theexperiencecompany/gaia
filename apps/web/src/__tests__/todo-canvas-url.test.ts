/**
 * Regression test for the tracked-todo canvas viewer.
 *
 * CanvasViewer hardcoded `/api/v1/todos/<id>/canvas`, but the axios baseURL
 * already ends in `/api/v1/`, so every open hit `/api/v1/api/v1/todos/...`
 * and 404'd. The shared `TODO_ENDPOINTS` map stays unprefixed for the shared
 * todo client, and the typed client trims the schema's `/api/v1` itself;
 * these assertions fail if either path grows a version prefix again.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

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

import { TODO_ENDPOINTS } from "@shared/api/todosApi";
import { getTodoCanvas } from "@/features/todo/api/todoApi";

describe("todo canvas endpoint", () => {
  it("builds an unprefixed path like every other todo endpoint", () => {
    expect(TODO_ENDPOINTS.canvas("todo-1")).toBe("/todos/todo-1/canvas");
    expect(TODO_ENDPOINTS.canvas("todo-1")).not.toContain("/api/");
  });
});

describe("getTodoCanvas", () => {
  beforeEach(() => {
    request.mockReset();
    request.mockResolvedValue({
      status: 200,
      headers: {},
      data: { content: "# canvas", activity: "- ran" },
    });
  });

  it("requests the canvas path exactly once under /api/v1", async () => {
    await getTodoCanvas("todo-1");
    expect(request).toHaveBeenCalledWith(
      expect.objectContaining({
        method: "GET",
        url: "http://localhost:8000/api/v1/todos/todo-1/canvas",
      }),
    );
  });

  it("returns both notes files", async () => {
    const res = await getTodoCanvas("todo-1");
    expect(res.content).toBe("# canvas");
    expect(res.activity).toBe("- ran");
  });
});

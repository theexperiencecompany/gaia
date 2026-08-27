/**
 * Regression test for the tracked-todo canvas viewer.
 *
 * CanvasViewer hardcoded `/api/v1/todos/<id>/canvas`, but the axios baseURL
 * already ends in `/api/v1/`, so every open hit `/api/v1/api/v1/todos/...`
 * and 404'd. The URL now lives in the shared `TODO_ENDPOINTS` map (unprefixed,
 * like every other todo endpoint); these assertions fail if a version prefix
 * ever sneaks back into it or if the fetch drifts off the shared constant.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/service", () => ({
  apiService: { get: vi.fn().mockResolvedValue({ content: "# canvas" }) },
}));

import { TODO_ENDPOINTS } from "@shared/api/todosApi";
import { getTodoCanvas } from "@/features/todo/api/todoApi";
import { apiService } from "@/lib/api/service";

describe("todo canvas endpoint", () => {
  it("builds an unprefixed path like every other todo endpoint", () => {
    expect(TODO_ENDPOINTS.canvas("todo-1")).toBe("/todos/todo-1/canvas");
    expect(TODO_ENDPOINTS.canvas("todo-1")).not.toContain("/api/");
  });
});

describe("getTodoCanvas", () => {
  beforeEach(() => {
    vi.mocked(apiService.get).mockClear();
  });

  it("fetches via the shared endpoint map with silent toasts", async () => {
    await getTodoCanvas("todo-1");
    expect(apiService.get).toHaveBeenCalledWith("/todos/todo-1/canvas", {
      silent: true,
    });
  });

  it("returns the canvas content", async () => {
    const res = await getTodoCanvas("todo-1");
    expect(res.content).toBe("# canvas");
  });
});

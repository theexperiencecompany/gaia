import { describe, expect, it } from "vitest";

import { isTrackedTodo } from "./tracked";

describe("isTrackedTodo", () => {
  it("is true for a todo with a canvas", () => {
    expect(
      isTrackedTodo({ vfs_path: "/workspace/gaia-tasks/x/canvas.md" }),
    ).toBe(true);
  });

  it("is false for a classic todo", () => {
    expect(isTrackedTodo({ vfs_path: null })).toBe(false);
    expect(isTrackedTodo({ vfs_path: "" })).toBe(false);
  });
});

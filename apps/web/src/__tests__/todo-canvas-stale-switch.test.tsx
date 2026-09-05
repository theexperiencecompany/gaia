// @vitest-environment jsdom
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getTodoCanvas } from "@/features/todo/api/todoApi";
import { useTodoCanvas } from "@/features/todo/hooks/useTodoCanvas";

/**
 * Regression test: switching the selected todo must show the newly selected
 * todo's canvas.md, not the previously opened one.
 *
 * The sidebar reuses one WorkLogSection — and so one useTodoCanvas instance —
 * across todo selections; only `todoId` changes. The hook previously cached the
 * fetched markdown and guarded the fetch with `if (content !== null) return`,
 * so todo A's content survived a switch to todo B: the guard short-circuited
 * the refetch and B's modal showed A's canvas until a full page refresh. The
 * hook now fetches on every open; reintroduce the cache guard and this fails.
 */

vi.mock("@/features/todo/api/todoApi", () => ({
  getTodoCanvas: vi.fn(async (todoId: string) => ({
    content: `# canvas for ${todoId}`,
  })),
  getTodoFacet: vi.fn(),
}));

describe("useTodoCanvas across todo switches", () => {
  beforeEach(() => {
    vi.mocked(getTodoCanvas).mockClear();
  });

  it("fetches the newly selected todo's canvas after opening, closing, and switching", async () => {
    const { result, rerender } = renderHook(
      ({ todoId, isOpen }: { todoId: string; isOpen: boolean }) =>
        useTodoCanvas(todoId, { auto: isOpen }),
      { initialProps: { todoId: "todo-a", isOpen: true } },
    );
    await waitFor(() =>
      expect(result.current.content).toBe("# canvas for todo-a"),
    );

    // Close the modal, then switch the selected todo to B and reopen it.
    rerender({ todoId: "todo-a", isOpen: false });
    rerender({ todoId: "todo-b", isOpen: true });

    await waitFor(() =>
      expect(result.current.content).toBe("# canvas for todo-b"),
    );
    expect(getTodoCanvas).toHaveBeenLastCalledWith("todo-b");
  });
});

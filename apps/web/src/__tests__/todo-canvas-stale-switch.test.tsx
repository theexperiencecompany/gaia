// @vitest-environment jsdom
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TodoSidebar } from "@/components/layout/sidebar/right-variants/TodoSidebar";
import { getTodoCanvas } from "@/features/todo/api/todoApi";
import { Priority, type Todo } from "@/types/features/todoTypes";

/**
 * Regression test: switching the selected todo must show the newly selected
 * todo's canvas.md, not the previously opened one.
 *
 * The sidebar reuses one CanvasViewer instance across todo selections (only the
 * props change). CanvasViewer previously cached the fetched markdown and guarded
 * the fetch with `if (content !== null) return`, so todo A's cached content
 * survived a switch to todo B — the guard short-circuited the refetch and B's
 * viewer showed A's canvas until a full page refresh. CanvasViewer now fetches
 * on every open; reintroduce the cache guard and this fails.
 */

vi.mock("@/features/auth/hooks/useUser", () => ({
  useUser: () => undefined,
}));

// Siblings pull in workflow fetches / selects that are irrelevant here.
vi.mock("@/features/todo/components/WorkflowSection", () => ({
  default: () => null,
}));
vi.mock("@/features/todo/components/shared/SubtaskManager", () => ({
  default: () => null,
}));
vi.mock("@/features/todo/components/shared/TodoFieldsRow", () => ({
  default: () => null,
}));

vi.mock("@/features/todo/api/todoApi", () => ({
  getTodoCanvas: vi.fn(async (todoId: string) => ({
    content: `# canvas for ${todoId}`,
  })),
}));

// Surface the content prop CanvasViewer computes without HeroUI's portal.
vi.mock("@/components/common/MarkdownViewerModal", () => ({
  default: ({
    isOpen,
    content,
    onClose,
  }: {
    isOpen: boolean;
    content: string | null;
    onClose: () => void;
  }) =>
    isOpen ? (
      <div data-testid="canvas-modal">
        <span data-testid="canvas-content">{content}</span>
        <button type="button" data-testid="canvas-close" onClick={onClose}>
          close
        </button>
      </div>
    ) : null,
}));

function makeTodo(id: string): Todo {
  return {
    id,
    user_id: "user-1",
    title: `Todo ${id}`,
    labels: [],
    priority: Priority.NONE,
    project_id: "project-1",
    completed: false,
    subtasks: [],
    vfs_path: `/todos/${id}/canvas.md`,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

const noop = vi.fn();

describe("TodoSidebar canvas.md across todo switches", () => {
  beforeEach(() => {
    vi.mocked(getTodoCanvas).mockClear();
  });

  it("shows the newly selected todo's canvas after opening, closing, and switching", async () => {
    const todoA = makeTodo("todo-a");
    const todoB = makeTodo("todo-b");

    const { rerender } = render(
      <TodoSidebar
        todo={todoA}
        onUpdate={noop}
        onDelete={noop}
        projects={[]}
      />,
    );

    // Open todo A's canvas.
    fireEvent.click(screen.getByText("canvas.md"));
    await waitFor(() =>
      expect(screen.getByTestId("canvas-content").textContent).toBe(
        "# canvas for todo-a",
      ),
    );

    // Close it, then switch the selected todo to B.
    fireEvent.click(screen.getByTestId("canvas-close"));
    rerender(
      <TodoSidebar
        todo={todoB}
        onUpdate={noop}
        onDelete={noop}
        projects={[]}
      />,
    );

    // Open B's canvas — it must fetch and show B, not the cached A.
    fireEvent.click(screen.getByText("canvas.md"));
    await waitFor(() =>
      expect(screen.getByTestId("canvas-content").textContent).toBe(
        "# canvas for todo-b",
      ),
    );
    expect(getTodoCanvas).toHaveBeenLastCalledWith("todo-b");
  });

  it("drops a late response for the previous todo after switching", async () => {
    const todoA = makeTodo("todo-a");
    const todoB = makeTodo("todo-b");

    // Hold A's fetch pending so it resolves after the switch.
    let resolveA!: (notes: { content: string; activity: string }) => void;
    vi.mocked(getTodoCanvas).mockImplementationOnce(
      () =>
        new Promise<{ content: string; activity: string }>((resolve) => {
          resolveA = resolve;
        }),
    );

    const { rerender } = render(
      <TodoSidebar
        todo={todoA}
        onUpdate={noop}
        onDelete={noop}
        projects={[]}
      />,
    );

    // Open A's canvas; the request stays in flight.
    fireEvent.click(screen.getByText("canvas.md"));

    // Switch the selected todo while A's request is pending, then let A resolve.
    rerender(
      <TodoSidebar
        todo={todoB}
        onUpdate={noop}
        onDelete={noop}
        projects={[]}
      />,
    );
    await act(async () => {
      resolveA({ content: "# canvas for todo-a", activity: "" });
    });

    // A's late response must be discarded, not shown under B's title.
    expect(screen.getByTestId("canvas-content").textContent).toBe("");

    // Close and open B's canvas — it fetches fresh and shows B.
    fireEvent.click(screen.getByTestId("canvas-close"));
    fireEvent.click(screen.getByText("canvas.md"));
    await waitFor(() =>
      expect(screen.getByTestId("canvas-content").textContent).toBe(
        "# canvas for todo-b",
      ),
    );
    expect(getTodoCanvas).toHaveBeenLastCalledWith("todo-b");
  });
});

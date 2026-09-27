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
import { makeTodo } from "./fixtures/todo";

/**
 * Regression test: switching the selected todo must show its own canvas.md.
 *
 * The sidebar reuses one CanvasViewer across selections; it used to cache
 * fetched markdown and guard with `if (content !== null) return`, so todo
 * A's content survived a switch to B until a full refresh. It now fetches
 * on every open — reintroduce the cache guard and this fails.
 */

vi.mock("@/features/auth/hooks/useCurrentUser", () => ({
  useCurrentUser: () => undefined,
}));

// Siblings pull in workflow fetches / selects that are irrelevant here.
vi.mock("@/features/todo/components/WorkflowSection", () => ({
  default: () => <div data-testid="workflow-section" />,
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

describe("TodoSidebar workflow section", () => {
  it("is hidden for a tracked todo, which runs on the agent from its canvas", () => {
    render(
      <TodoSidebar
        todo={makeTodo("todo-a")}
        onUpdate={noop}
        onDelete={noop}
        projects={[]}
      />,
    );

    expect(screen.queryByTestId("workflow-section")).toBeNull();
  });

  it("is shown for a classic todo", () => {
    render(
      <TodoSidebar
        todo={makeTodo("todo-a", { vfs_path: null })}
        onUpdate={noop}
        onDelete={noop}
        projects={[]}
      />,
    );

    expect(screen.getByTestId("workflow-section")).toBeTruthy();
  });
});

describe("TodoSidebar inline editors", () => {
  function renderSidebar() {
    const onUpdate = vi.fn();
    render(
      <TodoSidebar
        todo={makeTodo("todo-a", { vfs_path: null, description: "old notes" })}
        onUpdate={onUpdate}
        onDelete={noop}
        projects={[]}
      />,
    );
    return onUpdate;
  }

  it("saves an edited title on blur, trimmed", () => {
    const onUpdate = renderSidebar();
    fireEvent.click(screen.getByText("Todo todo-a"));
    const input = screen.getByDisplayValue("Todo todo-a");
    fireEvent.blur(input, { target: { value: "  Renamed  " } });

    expect(onUpdate).toHaveBeenCalledWith("todo-a", { title: "Renamed" });
    expect(screen.getByText("Todo todo-a")).toBeTruthy();
  });

  it("cancels a title edit on Escape without saving", () => {
    const onUpdate = renderSidebar();
    fireEvent.click(screen.getByText("Todo todo-a"));
    fireEvent.keyDown(screen.getByDisplayValue("Todo todo-a"), {
      key: "Escape",
    });

    expect(screen.queryByDisplayValue("Todo todo-a")).toBeNull();
    expect(onUpdate).not.toHaveBeenCalled();
  });

  it("saves an edited description on blur", () => {
    const onUpdate = renderSidebar();
    fireEvent.click(screen.getByText("old notes"));
    fireEvent.blur(screen.getByDisplayValue("old notes"), {
      target: { value: "new notes" },
    });

    expect(onUpdate).toHaveBeenCalledWith("todo-a", {
      description: "new notes",
    });
  });
});

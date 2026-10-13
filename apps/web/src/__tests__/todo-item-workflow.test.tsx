// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import TodoItem from "@/features/todo/components/TodoItem";
import { makeTodo } from "./fixtures/todo";

vi.mock("@/features/chat/utils/toolIcons", () => ({
  getToolCategoryIcon: () => <span data-testid="workflow-icon" />,
}));

afterEach(() => {
  vi.useRealTimers();
});

function renderRow(todo: ReturnType<typeof makeTodo>) {
  vi.useFakeTimers();
  const prefetch = vi.fn();
  const { container } = render(
    <QueryClientProvider client={new QueryClient()}>
      <TodoItem
        todo={todo}
        projects={[]}
        isSelected={false}
        onUpdate={vi.fn()}
        onPrefetchWorkflow={prefetch}
      />
    </QueryClientProvider>,
  );
  fireEvent.mouseEnter(container.firstChild as Element);
  // Hover intent is debounced — a fast mouse pass must not prefetch.
  vi.advanceTimersByTime(200);
  return { container, prefetch };
}

describe("TodoItem workflow surfaces", () => {
  it("shows no workflow icons and fetches no workflow for a tracked todo", () => {
    const { prefetch } = renderRow(
      makeTodo("todo-a", { workflow_categories: ["gmail", "slack"] }),
    );

    expect(screen.queryAllByTestId("workflow-icon")).toHaveLength(0);
    expect(prefetch).not.toHaveBeenCalled();
  });

  it("shows workflow icons and prefetches for a classic todo", () => {
    const { prefetch } = renderRow(
      makeTodo("todo-a", {
        vfs_path: null,
        workflow_categories: ["gmail", "slack"],
      }),
    );

    expect(screen.getAllByTestId("workflow-icon")).toHaveLength(2);
    expect(prefetch).toHaveBeenCalledWith("todo-a");
  });

  it("does not prefetch on a passing hover that leaves before the intent delay", () => {
    vi.useFakeTimers();
    const prefetch = vi.fn();
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <TodoItem
          todo={makeTodo("todo-b", { vfs_path: null })}
          projects={[]}
          isSelected={false}
          onUpdate={vi.fn()}
          onPrefetchWorkflow={prefetch}
        />
      </QueryClientProvider>,
    );
    fireEvent.mouseEnter(container.firstChild as Element);
    fireEvent.mouseLeave(container.firstChild as Element);
    vi.advanceTimersByTime(500);
    expect(prefetch).not.toHaveBeenCalled();
  });
});

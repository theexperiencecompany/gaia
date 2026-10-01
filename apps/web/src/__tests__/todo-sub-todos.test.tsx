// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { todoApi } from "@/features/todo/api/todoApi";
import { SubTodosSection } from "@/features/todo/components/SubTodosSection";
import TodoItem from "@/features/todo/components/TodoItem";
import { makeTodo } from "./fixtures/todo";

vi.mock("@/features/chat/utils/toolIcons", () => ({
  getToolCategoryIcon: () => <span />,
}));

vi.mock("@/features/todo/api/todoApi", () => ({
  todoApi: { getAllTodos: vi.fn() },
}));

function withQueryClient(node: React.ReactNode) {
  return (
    <QueryClientProvider client={new QueryClient()}>{node}</QueryClientProvider>
  );
}

describe("sub-todos", () => {
  it("a parent row shows how many open sub-todos it has", () => {
    render(
      withQueryClient(
        <TodoItem
          todo={makeTodo("desk", { sub_todo_count: 3 })}
          projects={[]}
          isSelected={false}
          onUpdate={vi.fn()}
          onPrefetchWorkflow={vi.fn()}
        />,
      ),
    );

    expect(screen.getByText("3 sub-todos")).toBeTruthy();
  });

  it("a row without sub-todos shows no count", () => {
    render(
      withQueryClient(
        <TodoItem
          todo={makeTodo("plain")}
          projects={[]}
          isSelected={false}
          onUpdate={vi.fn()}
          onPrefetchWorkflow={vi.fn()}
        />,
      ),
    );

    expect(screen.queryByText(/sub-todos/)).toBeNull();
  });

  it("the parent's detail lists each sub-todo, linked to its own detail", async () => {
    vi.mocked(todoApi.getAllTodos).mockResolvedValue([
      makeTodo("thread-1", {
        title: "Reply to Sam",
        labels: ["needs-reply"],
        parent_todo_id: "desk",
      }),
      makeTodo("thread-2", {
        title: "Lease renewal",
        completed: true,
        parent_todo_id: "desk",
      }),
    ]);

    render(
      withQueryClient(<SubTodosSection parentTodoId="desk" openCount={1} />),
    );

    const link = await screen.findByRole("link", { name: "Reply to Sam" });
    expect(link.getAttribute("href")).toBe("/todos?todoId=thread-1");
    expect(screen.getByText("needs-reply")).toBeTruthy();
    expect(screen.getByText("thread-2")).toBeTruthy();
    expect(screen.getByText("Completed")).toBeTruthy();
    expect(todoApi.getAllTodos).toHaveBeenCalledWith({
      parent_todo_id: "desk",
    });
  });
});

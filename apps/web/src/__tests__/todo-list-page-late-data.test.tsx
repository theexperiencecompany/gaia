// @vitest-environment jsdom
/** The list must render when its data lands after mount, as it does after in-app navigation to /todos. */

import { act, render, screen } from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import type { Todo } from "@/types/features/todoTypes";
import { makeTodo } from "./fixtures/todo";

vi.mock("@/features/todo/hooks/useUrlTodoSelection", () => ({
  useUrlTodoSelection: () => ({
    selectedTodoId: null,
    selectTodo: vi.fn(),
    clearSelection: vi.fn(),
  }),
}));
vi.mock("@/features/todo/hooks/useTodoData", () => ({
  useTodoData: () => ({
    updateTodo: vi.fn(),
    deleteTodo: vi.fn(),
    refresh: vi.fn(),
  }),
}));
vi.mock("@/features/auth/hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ timezone: undefined }),
}));
vi.mock("@/components/layout/sidebar/RightSidebarPanel", () => ({
  default: () => null,
}));
vi.mock("@/components/layout/sidebar/right-variants/TodoSidebar", () => ({
  TodoSidebar: () => null,
}));
vi.mock("@/features/todo/components/TodoItem", () => ({
  default: ({ todo }: { todo: Todo }) => <p>{todo.title}</p>,
}));

import TodoListPage from "@/features/todo/components/TodoListPage";
import { useTodoStore } from "@/stores/todoStore";

// jsdom lays nothing out; give the scroll container a viewport to fill.
const VIEWPORT_HEIGHT = 800;
const originalOffsetHeight = Object.getOwnPropertyDescriptor(
  HTMLElement.prototype,
  "offsetHeight",
);

beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, "offsetHeight", {
    configurable: true,
    get: () => VIEWPORT_HEIGHT,
  });
});

afterAll(() => {
  if (originalOffsetHeight) {
    Object.defineProperty(
      HTMLElement.prototype,
      "offsetHeight",
      originalOffsetHeight,
    );
  }
});

describe("TodoListPage", () => {
  it("renders rows that arrive after the skeleton", () => {
    useTodoStore.setState({ todos: [], initialLoading: true, error: null });
    render(<TodoListPage />);

    act(() => {
      useTodoStore.setState({
        todos: [
          makeTodo("plants", { title: "Water the plants" }),
          makeTodo("taxes", { title: "File taxes" }),
        ],
        initialLoading: false,
      });
    });

    expect(screen.getByText("Water the plants")).toBeTruthy();
    expect(screen.getByText("File taxes")).toBeTruthy();
  });
});

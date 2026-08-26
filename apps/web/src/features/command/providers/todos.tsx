"use client";

import {
  ArrowUpRight01Icon,
  CheckmarkCircle02Icon,
  Delete02Icon,
} from "@icons";
import type { Todo, TodoUpdate } from "@/types/features/todoTypes";
import { ACTION_ICON, ICON } from "../model/constants";
import type { BuildCtx, CommandItem } from "../model/types";

interface TodoDeps {
  updateTodo: (id: string, updates: TodoUpdate) => Promise<Todo>;
  deleteTodo: (id: string) => Promise<void>;
}

export const buildTodoItems = (
  todos: Todo[],
  ctx: BuildCtx,
  deps: TodoDeps,
): CommandItem[] =>
  todos.map((todo) => ({
    id: `todo:${todo.id}`,
    type: "todo",
    title: todo.title,
    subtitle: todo.due_date
      ? `Due ${todo.due_date}`
      : todo.priority && todo.priority !== "none"
        ? `${todo.priority} priority`
        : "No due date",
    icon: <CheckmarkCircle02Icon {...ICON} />,
    keywords: todo.priority ?? "",
    dot: todo.completed ? { color: "green", label: "Completed" } : undefined,
    primary: {
      id: "open",
      label: "Open todo",
      icon: <ArrowUpRight01Icon {...ACTION_ICON} />,
      run: ctx.navigate(`/todos?todoId=${todo.id}`),
    },
    actions: [
      {
        id: "toggle",
        label: todo.completed ? "Mark as incomplete" : "Mark as complete",
        icon: <CheckmarkCircle02Icon {...ACTION_ICON} />,
        run: async () => {
          await deps.updateTodo(todo.id, { completed: !todo.completed });
        },
      },
      {
        id: "delete",
        label: "Delete todo",
        icon: <Delete02Icon {...ACTION_ICON} />,
        destructive: true,
        run: async () => {
          const ok = await ctx.host.confirm({
            title: "Delete todo",
            message: `Delete "${todo.title}"?`,
            confirmText: "Delete",
            variant: "destructive",
          });
          if (!ok) return;
          await deps.deleteTodo(todo.id);
        },
      },
    ],
  }));

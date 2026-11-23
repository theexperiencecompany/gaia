import type { GateEdit, TodoCanvasResponse } from "@shared/api/generated";
import { createTodoApi } from "@shared/todos";
import { todoHttpAdapter } from "@/lib/api/todoHttpAdapter";
import { api } from "@/lib/api/typed";
import type { Todo } from "@/types/features/todoTypes";

export const todoApi = createTodoApi(todoHttpAdapter);

/** A tracked todo's notes: `content` is canvas.md, `activity` is activity.md. */
export type TodoNotes = TodoCanvasResponse;

export const getTodoCanvas = (todoId: string): Promise<TodoNotes> =>
  api.get("/api/v1/todos/{todo_id}/canvas", {
    path: { todo_id: todoId },
    silent: true,
  });

/** Store the user's edit to the gate on one of a tracked todo's run watches. */
export const editSubscriptionGate = (
  todoId: string,
  subscriptionId: string,
  edit: GateEdit,
): Promise<Todo> =>
  api.patch("/api/v1/todos/{todo_id}/subscriptions/{subscription_id}/gate", {
    path: { todo_id: todoId, subscription_id: subscriptionId },
    body: edit,
    errorMessage: "Couldn't save the condition",
  });

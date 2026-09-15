import type { TodoCanvasResponse } from "@shared/api/generated";
import { createTodoApi } from "@shared/todos";
import { todoHttpAdapter } from "@/lib/api/todoHttpAdapter";
import { api } from "@/lib/api/typed";

export const todoApi = createTodoApi(todoHttpAdapter);

/** A tracked todo's notes: `content` is canvas.md, `activity` is activity.md. */
export type TodoNotes = TodoCanvasResponse;

export const getTodoCanvas = (todoId: string): Promise<TodoNotes> =>
  api.get("/api/v1/todos/{todo_id}/canvas", {
    path: { todo_id: todoId },
    silent: true,
  });

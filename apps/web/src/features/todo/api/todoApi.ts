import { createTodoApi } from "@shared/todos";
import { todoHttpAdapter } from "@/lib/api/todoHttpAdapter";
import { api } from "@/lib/api/typed";

export const todoApi = createTodoApi(todoHttpAdapter);

export const getTodoCanvas = (todoId: string) =>
  api.get("/api/v1/todos/{todo_id}/canvas", {
    path: { todo_id: todoId },
    silent: true,
  });

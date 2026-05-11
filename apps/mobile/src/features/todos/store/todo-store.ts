import { createTodoStore } from "@gaia/shared/todos";
import { todoApi } from "../api/todo-api";

export const useTodoStore = createTodoStore(todoApi, {
  devtoolsName: "mobile-todo-store",
});

import { createTodoStore } from "@shared/todos";

import { todoApi } from "@/features/todo/api/todoApi";
import { toast } from "@/lib/toast";

export const useTodoStore = createTodoStore(todoApi, {
  notify: {
    success: (msg) => toast.success(msg),
    error: (msg) => toast.error(msg),
    info: (msg) => toast.info(msg),
  },
  devtoolsName: "todo-store",
});

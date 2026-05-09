import { createTodoStore } from "@shared/todos";

import { todoApi } from "@/features/todo/api/todoApi";
import { startWorkflowPolling } from "@/features/todo/hooks/useTodoWorkflowGlobalListener";
import { toast } from "@/lib/toast";

export const useTodoStore = createTodoStore(todoApi, {
  notify: {
    success: (msg) => toast.success(msg),
    error: (msg) => toast.error(msg),
    info: (msg) => toast.info(msg),
  },
  onTodoCreated: (todoId) => startWorkflowPolling(todoId),
  devtoolsName: "todo-store",
});

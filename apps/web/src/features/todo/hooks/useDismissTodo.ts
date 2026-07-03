"use client";

import { useMutation } from "@tanstack/react-query";
import axios from "axios";

import {
  type DismissTodoResponse,
  dismissTodo,
} from "@/features/todo/api/todoActionsApi";
import { toast } from "@/lib/toast";
import { useTodoStore } from "@/stores/todoStore";

interface DismissTodoVariables {
  todoId: string;
  reason?: string;
}

/**
 * Dismisses a GAIA-proposed todo. See `useApproveTodo` for why success is
 * handled as an optimistic store patch instead of a full list reload.
 *
 * 409 surfaces the server's `detail` message via a toast.
 */
export function useDismissTodo() {
  return useMutation<DismissTodoResponse, unknown, DismissTodoVariables>({
    mutationFn: ({ todoId, reason }) => dismissTodo(todoId, reason),
    onSuccess: (_data, { todoId }) => {
      useTodoStore
        .getState()
        .updateTodoOptimistic(todoId, { execution_status: "dismissed" });
      useTodoStore
        .getState()
        .loadCounts()
        .catch(() => undefined);
    },
    onError: (error) => {
      if (axios.isAxiosError(error) && error.response?.status === 409) {
        const detail = (error.response.data as { detail?: string })?.detail;
        toast.error(detail || "This task can't be dismissed right now.");
        return;
      }
      toast.error("Failed to dismiss task.");
    },
  });
}

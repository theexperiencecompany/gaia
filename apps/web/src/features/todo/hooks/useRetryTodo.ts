"use client";

import { useMutation } from "@tanstack/react-query";
import axios from "axios";

import {
  type RetryTodoResponse,
  retryTodo,
} from "@/features/todo/api/todoActionsApi";
import { toast } from "@/lib/toast";
import { useTodoStore } from "@/stores/todoStore";

/**
 * Re-runs a failed GAIA todo. Optimistically flips it back to `queued` in the
 * shared store (same patch mechanism as `useApproveTodo`); a 409 means the run
 * is no longer in a retryable state and surfaces the server's `detail`.
 */
export function useRetryTodo() {
  return useMutation<RetryTodoResponse, unknown, string>({
    mutationFn: (todoId: string) => retryTodo(todoId),
    onSuccess: (data, todoId) => {
      useTodoStore.getState().updateTodoOptimistic(todoId, {
        execution_status: data.execution_status,
        error_message: null,
      });
      useTodoStore
        .getState()
        .loadCounts()
        .catch(() => undefined);
    },
    onError: (error) => {
      if (axios.isAxiosError(error) && error.response?.status === 409) {
        const detail = (error.response.data as { detail?: string })?.detail;
        toast.error(detail || "This task can't be retried right now.");
        return;
      }
      toast.error("Failed to retry task.");
    },
  });
}

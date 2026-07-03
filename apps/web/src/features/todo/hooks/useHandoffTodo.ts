"use client";

import { useMutation } from "@tanstack/react-query";
import axios from "axios";

import {
  type HandoffTodoResponse,
  handoffTodo,
} from "@/features/todo/api/todoActionsApi";
import { toast } from "@/lib/toast";
import { useTodoStore } from "@/stores/todoStore";

/**
 * Hands a user-owned todo over to GAIA (used for the `gaia_offer` CTA). See
 * `useApproveTodo` for why success is handled as an optimistic store patch
 * instead of a full list reload.
 *
 * 409 surfaces the server's `detail` message via a toast.
 */
export function useHandoffTodo() {
  return useMutation<HandoffTodoResponse, unknown, string>({
    mutationFn: (todoId: string) => handoffTodo(todoId),
    onSuccess: (_data, todoId) => {
      useTodoStore.getState().updateTodoOptimistic(todoId, {
        assignee: "gaia",
        execution_status: "queued",
      });
      useTodoStore
        .getState()
        .loadCounts()
        .catch(() => undefined);
    },
    onError: (error) => {
      if (axios.isAxiosError(error) && error.response?.status === 409) {
        const detail = (error.response.data as { detail?: string })?.detail;
        toast.error(detail || "GAIA can't take this task right now.");
        return;
      }
      toast.error("Failed to hand off task.");
    },
  });
}

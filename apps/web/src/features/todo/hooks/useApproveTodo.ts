"use client";

import { useMutation } from "@tanstack/react-query";
import axios from "axios";

import {
  type ApproveTodoResponse,
  approveTodo,
  type GaiaExecutionQuotaError,
} from "@/features/todo/api/todoActionsApi";
import { toast } from "@/lib/toast";
import { usePricingModalStore } from "@/stores/pricingModalStore";
import { useTodoStore } from "@/stores/todoStore";

/**
 * Approves a GAIA-proposed todo, moving it into the execution queue.
 *
 * On success the affected todo is patched in place in the shared todo store
 * (the same optimistic-patch mechanism `useTodoWorkflowGlobalListener` uses
 * for websocket/polling updates) rather than reloading the whole list — a
 * full reload would blow away whatever filter the caller's list view is
 * currently showing.
 *
 * - 402 (`gaia_execution_quota`): opens the global pricing modal with the
 *   server's staged-work pitch instead of a generic error toast.
 * - 409: surfaces the server's `detail` message via a toast.
 */
export function useApproveTodo() {
  return useMutation<ApproveTodoResponse, unknown, string>({
    mutationFn: (todoId: string) => approveTodo(todoId),
    onSuccess: (data, todoId) => {
      useTodoStore.getState().updateTodoOptimistic(todoId, {
        execution_status: data.execution_status,
      });
      useTodoStore
        .getState()
        .loadCounts()
        .catch(() => undefined);
    },
    onError: (error) => {
      if (axios.isAxiosError(error)) {
        if (error.response?.status === 402) {
          const quotaError = error.response.data as
            | GaiaExecutionQuotaError
            | undefined;
          usePricingModalStore
            .getState()
            .openModal({ pitch: quotaError?.pitch });
          return;
        }
        if (error.response?.status === 409) {
          const detail = (error.response.data as { detail?: string })?.detail;
          toast.error(detail || "This task can't be approved right now.");
          return;
        }
      }
      toast.error("Failed to approve task.");
    },
  });
}

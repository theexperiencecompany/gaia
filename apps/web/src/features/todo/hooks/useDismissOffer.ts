"use client";

import { useMutation } from "@tanstack/react-query";

import {
  type DismissOfferResponse,
  dismissOffer,
} from "@/features/todo/api/todoActionsApi";
import { toast } from "@/lib/toast";
import { useTodoStore } from "@/stores/todoStore";

/**
 * Dismisses GAIA's takeover offer on a user todo. Patches `gaia_offer_dismissed`
 * into the shared store so every surface (sidebar banner, dashboard rows) hides
 * the affordance without a refetch.
 */
export function useDismissOffer() {
  return useMutation<DismissOfferResponse, unknown, string>({
    mutationFn: (todoId: string) => dismissOffer(todoId),
    onSuccess: (_data, todoId) => {
      useTodoStore
        .getState()
        .updateTodoOptimistic(todoId, { gaia_offer_dismissed: true });
    },
    onError: () => {
      toast.error("Failed to dismiss offer.");
    },
  });
}

import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { FirstStepsResponse } from "@/types/features/firstStepsTypes";
import { firstStepsApi } from "../api/firstStepsApi";
import { DISMISS_ALL_STEP } from "../constants";
import { FIRST_STEPS_QUERY_KEY } from "./useFirstStepsQuery";

/**
 * Dismisses the whole checklist for good, optimistically flipping `dismissed`
 * so the widget unmounts immediately. Mirrors the optimistic update +
 * invalidate-on-settle pattern in useHideFirstStepMutation.
 */
export const useDismissFirstStepsMutation = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => firstStepsApi.markFirstStep(DISMISS_ALL_STEP),
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: FIRST_STEPS_QUERY_KEY });

      const previous = queryClient.getQueryData<FirstStepsResponse>(
        FIRST_STEPS_QUERY_KEY,
      );

      queryClient.setQueryData<FirstStepsResponse>(
        FIRST_STEPS_QUERY_KEY,
        (old) => (old ? { ...old, dismissed: true } : old),
      );

      return { previous };
    },
    onError: (_error, _variables, context) => {
      if (context?.previous) {
        queryClient.setQueryData(FIRST_STEPS_QUERY_KEY, context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: FIRST_STEPS_QUERY_KEY });
    },
  });
};

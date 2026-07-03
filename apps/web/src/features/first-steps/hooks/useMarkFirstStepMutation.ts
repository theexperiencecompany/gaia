import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { FirstStepsResponse } from "@/types/features/firstStepsTypes";
import { firstStepsApi } from "../api/firstStepsApi";
import { FIRST_STEPS_QUERY_KEY } from "./useFirstStepsQuery";

/**
 * Marks a first-steps checklist item complete, optimistically stamping the
 * cache immediately so the widget updates without waiting on the round trip.
 * Mirrors the optimistic-update + invalidate-on-settle pattern used in
 * useEmailActions.
 */
export const useMarkFirstStepMutation = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (step: string) => firstStepsApi.markFirstStep(step),
    onMutate: async (step: string) => {
      await queryClient.cancelQueries({ queryKey: FIRST_STEPS_QUERY_KEY });

      const previous = queryClient.getQueryData<FirstStepsResponse>(
        FIRST_STEPS_QUERY_KEY,
      );

      queryClient.setQueryData<FirstStepsResponse>(
        FIRST_STEPS_QUERY_KEY,
        (old) => ({
          steps: {
            ...old?.steps,
            [step]: new Date().toISOString(),
          },
        }),
      );

      return { previous };
    },
    onError: (_error, _step, context) => {
      if (context?.previous) {
        queryClient.setQueryData(FIRST_STEPS_QUERY_KEY, context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: FIRST_STEPS_QUERY_KEY });
    },
  });
};

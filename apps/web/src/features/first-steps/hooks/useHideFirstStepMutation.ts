import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { FirstStepsResponse } from "@/types/features/firstStepsTypes";
import { firstStepsApi } from "../api/firstStepsApi";
import { FIRST_STEPS_QUERY_KEY } from "./useFirstStepsQuery";

/**
 * Hides a single checklist row server-side, optimistically adding it to
 * `hidden_steps` so the widget drops it immediately. Mirrors the optimistic
 * update + invalidate-on-settle pattern in useMarkFirstStepMutation.
 */
export const useHideFirstStepMutation = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (step: string) => firstStepsApi.hideFirstStep(step),
    onMutate: async (step: string) => {
      await queryClient.cancelQueries({ queryKey: FIRST_STEPS_QUERY_KEY });

      const previous = queryClient.getQueryData<FirstStepsResponse>(
        FIRST_STEPS_QUERY_KEY,
      );

      queryClient.setQueryData<FirstStepsResponse>(
        FIRST_STEPS_QUERY_KEY,
        (old) =>
          old
            ? {
                ...old,
                hidden_steps: old.hidden_steps.includes(step)
                  ? old.hidden_steps
                  : [...old.hidden_steps, step],
              }
            : old,
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

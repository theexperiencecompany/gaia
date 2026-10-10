import { useRouter } from "next/navigation";
import { useCallback } from "react";
import { FIRST_STEP_DEFINITIONS } from "@/features/first-steps/constants";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { useAppendToInput } from "@/stores/composerStore";
import type {
  FirstStepStatus,
  FirstStepsSurface,
} from "@/types/features/firstStepsTypes";

/**
 * Runs the thing a step asks for when its row is clicked. Completion is never
 * reported from here — the server derives `done` from what the user actually did.
 */
export function useFirstStepAction(
  surface: FirstStepsSurface,
): (step: FirstStepStatus) => void {
  const router = useRouter();
  const appendToInput = useAppendToInput();

  return useCallback(
    (step: FirstStepStatus) => {
      const { action } = FIRST_STEP_DEFINITIONS[step.key];
      // The row click is the only part of this the server cannot see.
      trackEvent(ANALYTICS_EVENTS.FIRST_STEPS_STEP_CLICKED, {
        step: step.key,
        done: step.done,
        surface,
      });
      if (action.kind === "chat") {
        // `appendToInput` seeds the composer and navigates to /c itself when
        // the user is not already there; a push here would double-navigate.
        appendToInput(action.prompt);
        return;
      }
      router.push(action.href);
    },
    [appendToInput, router, surface],
  );
}

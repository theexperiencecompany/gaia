import { useEffect } from "react";
import { useFirstStepsQuery } from "./useFirstStepsQuery";
import { useMarkFirstStepMutation } from "./useMarkFirstStepMutation";

/**
 * Marks a first-steps checklist item complete the moment its page mounts.
 * Call once from the top-level client component of the page that represents
 * that step (e.g. the workflows page for "explore_workflows"). Guards against
 * redundant PATCH calls by checking the already-loaded first-steps query data.
 */
export const useTrackRouteVisit = (step: string): void => {
  const { data } = useFirstStepsQuery();
  const { mutate: markFirstStep } = useMarkFirstStepMutation();

  useEffect(() => {
    if (!data) return;
    if (data.steps[step]) return;
    markFirstStep(step);
  }, [data, step, markFirstStep]);
};

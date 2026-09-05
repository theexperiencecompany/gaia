import { useEffect, useRef, useState } from "react";
import { toast } from "@/lib/toast";
import { FIRST_STEPS, type FirstStepDefinition } from "../constants";
import { useDismissFirstStepsMutation } from "./useDismissFirstStepsMutation";
import { useFirstStepsQuery } from "./useFirstStepsQuery";
import { useHideFirstStepMutation } from "./useHideFirstStepMutation";

// Minimizing the widget to the pill survives reloads; dismissing it for good
// is recorded server-side instead, so it holds across browsers.
const COLLAPSED_STORAGE_KEY = "gaia:first-steps:collapsed";

// The "all set up" celebration is a one-time event. The backend keeps reporting
// every step complete forever, so without a persisted flag the in-memory guard
// (which resets on each mount) re-fires the toast on every page load.
const CELEBRATED_STORAGE_KEY = "gaia:first-steps:celebrated";

function readCelebrated(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(CELEBRATED_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

interface UseFirstStepsWidgetResult {
  isReady: boolean;
  shouldRender: boolean;
  expanded: boolean;
  setExpanded: (expanded: boolean) => void;
  visibleSteps: FirstStepDefinition[];
  completedAt: Record<string, string | null>;
  completedCount: number;
  totalCount: number;
  hideStep: (stepKey: string) => void;
  dismiss: () => void;
}

export const useFirstStepsWidget = (): UseFirstStepsWidgetResult => {
  const { data, isLoading } = useFirstStepsQuery();
  const hideStepMutation = useHideFirstStepMutation();
  const dismissMutation = useDismissFirstStepsMutation();
  const [expanded, setExpandedState] = useState(true);
  const hasCelebrated = useRef(false);

  useEffect(() => {
    setExpandedState(
      window.localStorage.getItem(COLLAPSED_STORAGE_KEY) !== "true",
    );
    // Seed the guard from the persisted flag so a finished user isn't
    // re-congratulated on every reload.
    hasCelebrated.current = readCelebrated();
  }, []);

  const setExpanded = (next: boolean) => {
    setExpandedState(next);
    window.localStorage.setItem(COLLAPSED_STORAGE_KEY, String(!next));
  };

  const completedAt = data?.steps ?? {};
  const hiddenSteps = new Set(data?.hidden_steps ?? []);
  const hasHadProposal = data?.has_had_proposal ?? false;
  const dismissed = data?.dismissed ?? false;

  // The first_approve row is uncompletable until GAIA has ever proposed work,
  // so it isn't part of the checklist until then.
  const applicableSteps = FIRST_STEPS.filter(
    (step) => step.key !== "first_approve" || hasHadProposal,
  );
  const visibleSteps = applicableSteps.filter(
    (step) => !hiddenSteps.has(step.key),
  );
  const completedCount = applicableSteps.filter(
    (step) => completedAt[step.key],
  ).length;
  const totalCount = applicableSteps.length;
  const allComplete = totalCount > 0 && completedCount === totalCount;

  useEffect(() => {
    if (allComplete && !hasCelebrated.current) {
      hasCelebrated.current = true;
      window.localStorage.setItem(CELEBRATED_STORAGE_KEY, "true");
      toast.success("You're all set up! Nicely done.");
    }
  }, [allComplete]);

  const hideStep = (stepKey: string) => {
    hideStepMutation.mutate(stepKey);
  };

  const dismiss = () => {
    dismissMutation.mutate();
  };

  const isReady = !isLoading && Boolean(data);
  // Auto-closes for good once everything is complete (the celebration toast
  // is the goodbye); dismissing closes it early and permanently.
  const shouldRender =
    isReady && !dismissed && !allComplete && visibleSteps.length > 0;

  return {
    isReady,
    shouldRender,
    expanded,
    setExpanded,
    visibleSteps,
    completedAt,
    completedCount,
    totalCount,
    hideStep,
    dismiss,
  };
};

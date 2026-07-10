import { useEffect, useRef, useState } from "react";
import { toast } from "@/lib/toast";
import { FIRST_STEPS, type FirstStepDefinition } from "../constants";
import { useFirstStepsQuery } from "./useFirstStepsQuery";

// Client-only: the backend contract only exposes per-step *completion*, not a
// per-step dismissal endpoint. Hiding a single row without marking it complete
// is therefore tracked locally per browser.
const HIDDEN_STEPS_STORAGE_KEY = "gaia:first-steps:hidden-steps";

// Closing the widget minimizes it to the pill; that choice survives reloads.
const COLLAPSED_STORAGE_KEY = "gaia:first-steps:collapsed";

function readHiddenSteps(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(HIDDEN_STEPS_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

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
}

export const useFirstStepsWidget = (): UseFirstStepsWidgetResult => {
  const { data, isLoading } = useFirstStepsQuery();
  const [expanded, setExpandedState] = useState(true);
  const [hiddenSteps, setHiddenSteps] = useState<string[]>([]);
  const hasCelebrated = useRef(false);

  useEffect(() => {
    setHiddenSteps(readHiddenSteps());
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
  const visibleSteps = FIRST_STEPS.filter(
    (step) => !hiddenSteps.includes(step.key),
  );
  const completedCount = FIRST_STEPS.filter(
    (step) => completedAt[step.key],
  ).length;
  const allComplete =
    FIRST_STEPS.length > 0 && completedCount === FIRST_STEPS.length;

  useEffect(() => {
    if (allComplete && !hasCelebrated.current) {
      hasCelebrated.current = true;
      window.localStorage.setItem(CELEBRATED_STORAGE_KEY, "true");
      toast.success("You're all set up! Nicely done.");
    }
  }, [allComplete]);

  const hideStep = (stepKey: string) => {
    const next = [...hiddenSteps, stepKey];
    setHiddenSteps(next);
    window.localStorage.setItem(HIDDEN_STEPS_STORAGE_KEY, JSON.stringify(next));
  };

  const isReady = !isLoading && Boolean(data);
  // Auto-closes for good once everything is complete (the celebration toast
  // is the goodbye) — no dismissal path needed beyond minimizing.
  const shouldRender = isReady && !allComplete && visibleSteps.length > 0;

  return {
    isReady,
    shouldRender,
    expanded,
    setExpanded,
    visibleSteps,
    completedAt,
    completedCount,
    totalCount: FIRST_STEPS.length,
    hideStep,
  };
};

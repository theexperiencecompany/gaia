import { create } from "zustand";
import { devtools } from "zustand/middleware";

export type ContextStatus =
  | "idle"
  | "gathering"
  | "parsing_emails"
  | "building_graph"
  | "complete"
  | "error";

export enum OnboardingPhase {
  INITIAL = "initial",
  PERSONALIZATION_PENDING = "personalization_pending",
  PERSONALIZATION_COMPLETE = "personalization_complete",
  GETTING_STARTED = "getting_started",
  COMPLETED = "completed",
}

interface OnboardingState {
  contextStatus: ContextStatus;
  contextMessage: string | null;
  phase: OnboardingPhase | null;
  isPhaseLoading: boolean;
}

interface OnboardingActions {
  setContextStatus: (status: ContextStatus) => void;
  setContextMessage: (message: string | null) => void;
  setPhase: (phase: OnboardingPhase | null) => void;
  setPhaseLoading: (loading: boolean) => void;
  reset: () => void;
}

type OnboardingStore = OnboardingState & OnboardingActions;

const initialState: OnboardingState = {
  contextStatus: "idle",
  contextMessage: null,
  phase: null,
  isPhaseLoading: false,
};

export const useOnboardingStore = create<OnboardingStore>()(
  devtools(
    (set) => ({
      ...initialState,
      setContextStatus: (status) => set({ contextStatus: status }),
      setContextMessage: (message) => set({ contextMessage: message }),
      setPhase: (phase) => set({ phase }),
      setPhaseLoading: (loading) => set({ isPhaseLoading: loading }),
      reset: () => set(initialState),
    }),
    { name: "onboarding-store" },
  ),
);

// Export a specific hook for phase management for convenience
export const useOnboardingPhaseStore = () => {
  const { phase, isPhaseLoading, setPhase, setPhaseLoading } =
    useOnboardingStore();
  return {
    phase,
    isLoading: isPhaseLoading,
    setPhase,
    setLoading: setPhaseLoading,
  };
};

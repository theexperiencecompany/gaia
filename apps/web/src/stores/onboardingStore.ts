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
  /** Set when personalization completes — holo card can be shown after user activity */
  holoCardReady: boolean;
  /** Whether the holo card has already been shown this session */
  holoCardShown: boolean;
  /** Number of messages sent after onboarding completes */
  messagesSentAfterOnboarding: number;
}

interface OnboardingActions {
  setContextStatus: (status: ContextStatus) => void;
  setContextMessage: (message: string | null) => void;
  setPhase: (phase: OnboardingPhase | null) => void;
  setPhaseLoading: (loading: boolean) => void;
  setHoloCardReady: (ready: boolean) => void;
  setHoloCardShown: (shown: boolean) => void;
  incrementMessagesSent: () => void;
  reset: () => void;
}

type OnboardingStore = OnboardingState & OnboardingActions;

const initialState: OnboardingState = {
  contextStatus: "idle",
  contextMessage: null,
  phase: null,
  isPhaseLoading: false,
  holoCardReady: false,
  holoCardShown: false,
  messagesSentAfterOnboarding: 0,
};

export const useOnboardingStore = create<OnboardingStore>()(
  devtools(
    (set) => ({
      ...initialState,
      setContextStatus: (status) => set({ contextStatus: status }),
      setContextMessage: (message) => set({ contextMessage: message }),
      setPhase: (phase) => set({ phase }),
      setPhaseLoading: (loading) => set({ isPhaseLoading: loading }),
      setHoloCardReady: (ready) => set({ holoCardReady: ready }),
      setHoloCardShown: (shown) => set({ holoCardShown: shown }),
      incrementMessagesSent: () =>
        set((state) => ({
          messagesSentAfterOnboarding: state.messagesSentAfterOnboarding + 1,
        })),
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

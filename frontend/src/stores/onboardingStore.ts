import { create } from "zustand";
import { devtools } from "zustand/middleware";

export type ContextStatus =
  | "idle"
  | "gathering"
  | "parsing_emails"
  | "building_graph"
  | "complete"
  | "error";

interface OnboardingState {
  contextStatus: ContextStatus;
  contextMessage: string | null;
}

interface OnboardingActions {
  setContextStatus: (status: ContextStatus) => void;
  setContextMessage: (message: string | null) => void;
  reset: () => void;
}

type OnboardingStore = OnboardingState & OnboardingActions;

const initialState: OnboardingState = {
  contextStatus: "idle",
  contextMessage: null,
};

export const useOnboardingStore = create<OnboardingStore>()(
  devtools(
    (set) => ({
      ...initialState,
      setContextStatus: (status) => set({ contextStatus: status }),
      setContextMessage: (message) => set({ contextMessage: message }),
      reset: () => set(initialState),
    }),
    { name: "onboarding-store" },
  ),
);

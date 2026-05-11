import { create } from "zustand";

export interface WorkflowModalState {
  // Creation/Edit flow states
  creationPhase: "form" | "creating" | "generating" | "success" | "error";

  // Loading states
  isGeneratingSteps: boolean;
  isRegeneratingSteps: boolean;
  isTogglingActivation: boolean;

  // Error states
  regenerationError: string | null;
  creationError: string | null;

  // Modal-specific states
  countdown: number;
  countdownInterval: NodeJS.Timeout | null;

  // Workflow activation state
  isActivated: boolean;

  // Actions
  setCreationPhase: (phase: WorkflowModalState["creationPhase"]) => void;
  setIsGeneratingSteps: (loading: boolean) => void;
  setIsRegeneratingSteps: (loading: boolean) => void;
  setIsTogglingActivation: (loading: boolean) => void;
  setRegenerationError: (error: string | null) => void;
  setCreationError: (error: string | null) => void;
  setCountdown: (count: number) => void;
  setCountdownInterval: (interval: NodeJS.Timeout | null) => void;
  setIsActivated: (activated: boolean) => void;

  // Complex actions
  startCountdown: (seconds: number, onComplete: () => void) => void;
  clearCountdown: () => void;
  resetToForm: () => void;
  resetAll: () => void;
}

export const useWorkflowModalStore = create<WorkflowModalState>((set, get) => ({
  // Initial state
  creationPhase: "form",
  isGeneratingSteps: false,
  isRegeneratingSteps: false,
  isTogglingActivation: false,
  regenerationError: null,
  creationError: null,
  countdown: 0,
  countdownInterval: null,
  isActivated: true,

  // Basic setters
  setCreationPhase: (phase) => set({ creationPhase: phase }),
  setIsGeneratingSteps: (loading) => set({ isGeneratingSteps: loading }),
  setIsRegeneratingSteps: (loading) => set({ isRegeneratingSteps: loading }),
  setIsTogglingActivation: (loading) => set({ isTogglingActivation: loading }),
  setRegenerationError: (error) => set({ regenerationError: error }),
  setCreationError: (error) => set({ creationError: error }),
  setCountdown: (count) => set({ countdown: count }),
  setCountdownInterval: (interval) => set({ countdownInterval: interval }),
  setIsActivated: (activated) => set({ isActivated: activated }),

  // Complex actions
  startCountdown: (seconds, onComplete) => {
    const { clearCountdown } = get();
    clearCountdown(); // Clear any existing countdown

    set({ countdown: seconds });

    const interval = setInterval(() => {
      set((state) => {
        const newCount = state.countdown - 1;
        if (newCount <= 0) {
          clearInterval(interval);
          set({ countdownInterval: null, countdown: 0 });
          onComplete();
          return { countdown: 0 };
        }
        return { countdown: newCount };
      });
    }, 1000);

    set({ countdownInterval: interval });
  },

  clearCountdown: () => {
    const { countdownInterval } = get();
    if (countdownInterval) {
      clearInterval(countdownInterval);
      set({ countdownInterval: null, countdown: 0 });
    }
  },

  resetToForm: () => {
    const { clearCountdown } = get();
    clearCountdown();
    set({
      creationPhase: "form",
      isGeneratingSteps: false,
      isRegeneratingSteps: false,
      regenerationError: null,
      creationError: null,
    });
  },

  resetAll: () => {
    const { clearCountdown } = get();
    clearCountdown();
    set({
      creationPhase: "form",
      isGeneratingSteps: false,
      isRegeneratingSteps: false,
      isTogglingActivation: false,
      regenerationError: null,
      creationError: null,
      countdown: 0,
      countdownInterval: null,
      isActivated: true,
    });
  },
}));

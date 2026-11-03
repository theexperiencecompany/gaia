import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";
import type { ConceptId } from "./concepts";

interface PaywallLabFeedbackState {
  overall: string;
  notes: Partial<Record<ConceptId, string>>;
  setOverall: (overall: string) => void;
  setNote: (id: ConceptId, note: string) => void;
  clear: () => void;
}

export const usePaywallLabFeedback = create<PaywallLabFeedbackState>()(
  devtools(
    persist(
      (set) => ({
        overall: "",
        notes: {},
        setOverall: (overall) => set({ overall }, false, "setOverall"),
        setNote: (id, note) =>
          set(
            (state) => ({ notes: { ...state.notes, [id]: note } }),
            false,
            "setNote",
          ),
        clear: () => set({ overall: "", notes: {} }, false, "clear"),
      }),
      {
        // Per round: round 1 notes were about concepts that no longer exist.
        name: "gaia-paywall-lab-feedback-round-2",
        partialize: ({ overall, notes }) => ({ overall, notes }),
      },
    ),
    { name: "paywall-lab-feedback" },
  ),
);

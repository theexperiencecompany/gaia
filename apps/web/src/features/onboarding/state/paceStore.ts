/**
 * Which paced GAIA turns have finished "typing" this session. Keyed by turn
 * (`q-1`, `q-2`, `payment`, `platform`) so a re-render, a stage bounce or the
 * transcript re-deriving never replays a reveal, while a restart wipes it so
 * the wizard is paced again from the top.
 */

import { create } from "zustand";

interface PaceState {
  done: Record<string, true>;
  markDone: (key: string) => void;
  reset: () => void;
}

export const usePaceStore = create<PaceState>((set) => ({
  done: {},
  markDone: (key) =>
    set((s) => (s.done[key] ? s : { done: { ...s.done, [key]: true } })),
  reset: () => set({ done: {} }),
}));

/** Reveal key for the question with this id. */
export const questionRevealKey = (questionId: string) => `q-${questionId}`;

export const selectPaceDone = (key: string) => (s: PaceState) => !!s.done[key];

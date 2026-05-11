import { create } from "zustand";

interface ComposerState {
  pendingPrompt: string | null;
  appendToInput: (text: string) => void;
  consumePendingPrompt: () => string | null;
}

/**
 * Lightweight composer bridge.
 *
 * OpenUI action buttons (and any other in-chat trigger that needs to
 * populate the composer input) call `appendToInput`. The chat screen
 * reads `pendingPrompt` via `consumePendingPrompt` to hydrate its local
 * text state, then clears it.
 */
export const useComposerStore = create<ComposerState>((set, get) => ({
  pendingPrompt: null,
  appendToInput: (text) => set({ pendingPrompt: text }),
  consumePendingPrompt: () => {
    const { pendingPrompt } = get();
    if (pendingPrompt) set({ pendingPrompt: null });
    return pendingPrompt;
  },
}));

export const useAppendToInput = () =>
  useComposerStore((state) => state.appendToInput);

export const usePendingPrompt = () =>
  useComposerStore((state) => state.pendingPrompt);

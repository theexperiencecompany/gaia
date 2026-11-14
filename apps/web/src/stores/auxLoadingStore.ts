import { create } from "zustand";

import { getRandomThinkingMessage } from "@/utils/playfulThinking";

/** Loading UI owned by flows outside the conversation stream: the voice agent and file uploads. */
export interface AuxLoading {
  text: string;
}

interface AuxLoadingState {
  auxLoading: AuxLoading | null;
  setAuxLoading: (active: boolean, text?: string) => void;
}

export const useAuxLoadingStore = create<AuxLoadingState>()((set) => ({
  auxLoading: null,
  setAuxLoading: (active, text) =>
    set({
      auxLoading: active ? { text: text ?? getRandomThinkingMessage() } : null,
    }),
}));

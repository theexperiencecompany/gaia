import { create } from "zustand";

import { getRandomThinkingMessage } from "@/utils/playfulThinking";

export interface ActiveToolInfo {
  toolName?: string;
  toolCategory?: string;
  integrationName?: string;
  iconUrl?: string;
  showCategory?: boolean;
}

/** Loading UI owned by flows outside the conversation stream: the voice agent and file uploads. */
export interface AuxLoading {
  text: string;
  toolInfo?: ActiveToolInfo;
}

interface AuxLoadingState {
  auxLoading: AuxLoading | null;
  setAuxLoading: (
    active: boolean,
    text?: string,
    toolInfo?: ActiveToolInfo,
  ) => void;
}

export const useAuxLoadingStore = create<AuxLoadingState>()((set) => ({
  auxLoading: null,
  setAuxLoading: (active, text, toolInfo) =>
    set({
      auxLoading: active
        ? { text: text ?? getRandomThinkingMessage(), toolInfo }
        : null,
    }),
}));

import { create } from "zustand";
import { devtools } from "zustand/middleware";

import {
  getRandomThinkingMessage,
  getRelevantThinkingMessage,
} from "@/utils/playfulThinking";

interface ToolInfo {
  toolName?: string;
  toolCategory?: string;
  integrationName?: string;
  iconUrl?: string;
  showCategory?: boolean;
}

interface LoadingState {
  isLoading: boolean;
  // True only while the comms agent is producing its INITIAL response — from
  // send until `main_response_complete`. Unlike `isLoading` (which stays true
  // through the background-executor phase to keep the loading animation alive),
  // this clears once the agent has acknowledged the task ("on it"), which is
  // when the composer unlocks so the user can queue the next message.
  isMainResponseStreaming: boolean;
  loadingText: string;
  loadingTextKey: number;
  toolInfo?: ToolInfo;
}

interface LoadingActions {
  setIsLoading: (loading: boolean) => void;
  setMainResponseStreaming: (streaming: boolean) => void;
  setLoadingText: (
    text: string | { text: string; toolInfo?: ToolInfo },
  ) => void;
  resetLoadingText: () => void;
  setLoading: (loading: boolean, text?: string) => void;
  setLoadingWithContext: (
    loading: boolean,
    userMessage?: string,
    text?: string,
  ) => void;
}

type LoadingStore = LoadingState & LoadingActions;

const getInitialLoadingText = () => getRandomThinkingMessage();

const initialState: LoadingState = {
  isLoading: false,
  isMainResponseStreaming: false,
  loadingText: getInitialLoadingText(),
  loadingTextKey: 0,
  toolInfo: undefined,
};

export const useLoadingStore = create<LoadingStore>()(
  devtools(
    (set) => ({
      ...initialState,

      setIsLoading: (isLoading) => {
        if (isLoading) {
          set(
            (state) => ({
              isLoading,
              loadingText: getRandomThinkingMessage(),
              loadingTextKey: state.loadingTextKey + 1,
            }),
            false,
            "setIsLoading",
          );
        } else {
          set({ isLoading }, false, "setIsLoading");
        }
      },

      setMainResponseStreaming: (isMainResponseStreaming) =>
        set({ isMainResponseStreaming }, false, "setMainResponseStreaming"),

      setLoadingText: (payload) => {
        set(
          (state) => ({
            loadingText: typeof payload === "string" ? payload : payload.text,
            toolInfo:
              typeof payload === "string" ? undefined : payload.toolInfo,
            loadingTextKey: state.loadingTextKey + 1,
          }),
          false,
          "setLoadingText",
        );
      },

      resetLoadingText: () =>
        set(
          (state) => ({
            loadingText: getRandomThinkingMessage(),
            toolInfo: undefined,
            loadingTextKey: state.loadingTextKey + 1,
          }),
          false,
          "resetLoadingText",
        ),

      setLoading: (isLoading, text) => {
        set(
          (state) => {
            const updates: Partial<LoadingState> & { loadingTextKey: number } =
              {
                isLoading,
                loadingTextKey: state.loadingTextKey + 1,
              };
            if (text !== undefined) updates.loadingText = text;
            else if (isLoading)
              updates.loadingText = getRandomThinkingMessage();
            return updates;
          },
          false,
          "setLoading",
        );
      },

      setLoadingWithContext: (isLoading, userMessage, text) => {
        set(
          (state) => {
            const updates: Partial<LoadingState> & { loadingTextKey: number } =
              {
                isLoading,
                loadingTextKey: state.loadingTextKey + 1,
              };
            // This is the send-time loading trigger — the initial response is
            // now streaming, so lock the composer until main_response_complete.
            if (isLoading) updates.isMainResponseStreaming = true;
            if (text !== undefined) updates.loadingText = text;
            else if (isLoading) {
              updates.loadingText = userMessage?.trim()
                ? getRelevantThinkingMessage(userMessage)
                : getRandomThinkingMessage();
            }
            return updates;
          },
          false,
          "setLoadingWithContext",
        );
      },
    }),
    { name: "loading-store" },
  ),
);

// Selectors
export const useIsMainResponseStreaming = () =>
  useLoadingStore((state) => state.isMainResponseStreaming);

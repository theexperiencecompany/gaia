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
  loadingText: string;
  loadingTextKey: number;
  toolInfo?: ToolInfo;
}

interface LoadingActions {
  setIsLoading: (loading: boolean) => void;
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
export const useIsLoading = () => useLoadingStore((state) => state.isLoading);
export const useLoadingText = () =>
  useLoadingStore((state) => state.loadingText);
export const useToolInfo = () => useLoadingStore((state) => state.toolInfo);

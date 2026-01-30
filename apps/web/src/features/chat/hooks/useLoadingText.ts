"use client";
import { useLoadingStore } from "@/stores/loadingStore";

interface ToolInfo {
  toolName?: string;
  toolCategory?: string;
  integrationName?: string;
  iconUrl?: string;
  showCategory?: boolean;
}

export const useLoadingText = () => {
  const {
    loadingText,
    loadingTextKey,
    toolInfo,
    setLoadingText,
    resetLoadingText,
    setLoadingWithContext,
  } = useLoadingStore();

  const updateLoadingText = (text: string, toolInfo?: ToolInfo) => {
    if (toolInfo) {
      setLoadingText({ text, toolInfo });
    } else {
      setLoadingText(text);
    }
  };

  const setContextualLoading = (
    isLoading: boolean,
    userMessage?: string,
    text?: string,
  ) => {
    setLoadingWithContext(isLoading, userMessage, text);
  };

  return {
    loadingText,
    loadingTextKey,
    toolInfo,
    setLoadingText: updateLoadingText,
    setContextualLoading,
    resetLoadingText,
  };
};

"use client";
import { useLoadingStore } from "@/stores/loadingStore";

interface ToolInfo {
  toolName?: string;
  toolCategory?: string;
}

export const useLoadingText = () => {
  const {
    loadingText,
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
    toolInfo,
    setLoadingText: updateLoadingText,
    setContextualLoading,
    resetLoadingText,
  };
};

"use client";
import { type ToolInfo, useLoadingStore } from "@/stores/loadingStore";

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

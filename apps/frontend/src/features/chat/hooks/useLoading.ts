"use client";
import { useCallback } from "react";

import { streamController } from "@/features/chat/utils/streamController";
import { useLoadingStore } from "@/stores/loadingStore";

export const useLoading = () => {
  const { isLoading, setIsLoading } = useLoadingStore();

  const setLoadingState = useCallback(
    (loading: boolean) => {
      setIsLoading(loading);
    },
    [setIsLoading],
  );

  const setAbortController = useCallback(
    (controller: AbortController | null) => {
      streamController.set(controller);
    },
    [],
  );

  const stopStream = useCallback(() => {
    // Trigger the save before aborting the stream
    streamController.triggerSave();

    const aborted = streamController.abort();
    if (aborted) {
      setLoadingState(false);
    }
  }, [setLoadingState]);

  return {
    isLoading,
    setIsLoading: setLoadingState,
    setAbortController,
    stopStream,
  };
};

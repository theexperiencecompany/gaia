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

  // stopStream is now async to properly await the save callback before aborting
  // The UI will still update correctly because setLoadingState is called after await
  const stopStream = useCallback(async () => {
    const aborted = await streamController.abort();
    if (aborted) {
      setLoadingState(false);
      // A signal abort never triggers fetch-event-source's onclose/onerror, so
      // none of the stream-close handlers run. Clear the initial-response lock
      // here too, otherwise the composer stays locked and the Stop button never
      // reverts to Send (it keys off isMainResponseStreaming).
      useLoadingStore.getState().setMainResponseStreaming(false);
    }
  }, [setLoadingState]);

  return {
    isLoading,
    setIsLoading: setLoadingState,
    setAbortController,
    stopStream,
  };
};

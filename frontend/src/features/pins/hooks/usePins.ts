import { useCallback, useState } from "react";

import type { PinCardProps } from "@/types/features/pinTypes";

import { pinsApi } from "../api/pinsApi";

export const usePins = () => {
  const [pins, setPins] = useState<PinCardProps[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const fetchPins = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await pinsApi.fetchPins();
      setPins(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch pins");
    } finally {
      setLoading(false);
    }
  }, []);

  const pinMessage = useCallback(
    async (messageId: string): Promise<void> => {
      try {
        setError(null);
        await pinsApi.pinMessage(messageId);
        // Refresh pins after pinning
        await fetchPins();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to pin message");
        throw err;
      }
    },
    [fetchPins],
  );

  const unpinMessage = useCallback(async (messageId: string): Promise<void> => {
    try {
      setError(null);
      await pinsApi.unpinMessage(messageId);
      // Remove from local state immediately
      setPins((prev) =>
        prev.filter((pin) => pin.message.message_id !== messageId),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to unpin message");
      throw err;
    }
  }, []);

  return {
    pins,
    loading,
    error,
    fetchPins,
    pinMessage,
    unpinMessage,
  };
};

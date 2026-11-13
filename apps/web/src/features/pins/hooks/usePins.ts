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

  return {
    pins,
    loading,
    error,
    fetchPins,
  };
};

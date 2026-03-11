import { useCallback, useEffect, useState } from "react";
import type { Memory } from "../api/memory-api";
import { memoryApi } from "../api/memory-api";

interface UseMemoryState {
  memories: Memory[];
  isLoading: boolean;
  isRefreshing: boolean;
  error: string | null;
  search: string;
}

interface UseMemoryReturn extends UseMemoryState {
  setSearch: (search: string) => void;
  refetch: () => Promise<void>;
  createMemory: (content: string) => Promise<void>;
  deleteMemory: (id: string) => Promise<void>;
  clearAll: () => Promise<void>;
}

export function useMemory(): UseMemoryReturn {
  const [state, setState] = useState<UseMemoryState>({
    memories: [],
    isLoading: true,
    isRefreshing: false,
    error: null,
    search: "",
  });

  const fetchMemories = useCallback(
    async (search: string, isRefresh = false) => {
      setState((prev) => ({
        ...prev,
        isLoading: !isRefresh,
        isRefreshing: isRefresh,
        error: null,
      }));

      try {
        const response = await memoryApi.getMemories(search || undefined);
        setState((prev) => ({
          ...prev,
          memories: response.memories ?? [],
          isLoading: false,
          isRefreshing: false,
        }));
      } catch (err) {
        setState((prev) => ({
          ...prev,
          isLoading: false,
          isRefreshing: false,
          error: err instanceof Error ? err.message : "Failed to load memories",
        }));
      }
    },
    [],
  );

  useEffect(() => {
    void fetchMemories(state.search);
  }, [state.search, fetchMemories]);

  const setSearch = useCallback((search: string) => {
    setState((prev) => ({ ...prev, search }));
  }, []);

  const refetch = useCallback(async () => {
    await fetchMemories(state.search, true);
  }, [fetchMemories, state.search]);

  const createMemory = useCallback(
    async (content: string) => {
      await memoryApi.createMemory(content);
      await fetchMemories(state.search, true);
    },
    [fetchMemories, state.search],
  );

  const deleteMemory = useCallback(
    async (id: string) => {
      setState((prev) => ({
        ...prev,
        memories: prev.memories.filter((m) => m.id !== id),
      }));
      try {
        await memoryApi.deleteMemory(id);
      } catch {
        await fetchMemories(state.search, true);
      }
    },
    [fetchMemories, state.search],
  );

  const clearAll = useCallback(async () => {
    setState((prev) => ({ ...prev, memories: [] }));
    try {
      await memoryApi.clearAllMemory();
    } catch {
      await fetchMemories(state.search, true);
    }
  }, [fetchMemories, state.search]);

  return {
    ...state,
    setSearch,
    refetch,
    createMemory,
    deleteMemory,
    clearAll,
  };
}

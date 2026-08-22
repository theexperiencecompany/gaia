"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { memoryApi } from "@/features/memory/api/memoryApi";
import type { MemoryEntry } from "@/features/memory/api/types";
import {
  type ComprehensiveSearchResponse,
  searchApi,
} from "@/features/search/api/searchApi";

const DEBOUNCE_MS = 250;
export const MIN_CHARS = 2;

interface ChatSearchResult {
  results: ComprehensiveSearchResponse | undefined;
  isFetching: boolean;
  /**
   * The query the current results answer. During the debounce window this
   * trails the live input — callers must not render these rows against a
   * newer query, or stale hits linger under the floor score.
   */
  debounced: string;
}

/** Debounced server-side search over conversations + messages. */
export function useChatSearch(query: string): ChatSearchResult {
  const { isAuthenticated, userEmail } = useAuth();
  const [debounced, setDebounced] = useState("");

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(query.trim()), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query]);

  const { data, isFetching } = useQuery({
    // Keyed to the user so cached results never leak across sessions.
    queryKey: ["command-k", "search", userEmail, debounced],
    queryFn: async () => {
      // search:performed is captured by the API (single source of truth);
      // no client-side capture here.
      return searchApi.search(debounced);
    },
    enabled: isAuthenticated && debounced.length >= MIN_CHARS,
    staleTime: 30_000,
  });

  return { results: data, isFetching, debounced };
}

interface MemorySearchResult {
  memories: MemoryEntry[];
  isFetching: boolean;
  /** See ChatSearchResult.debounced — same staleness contract. */
  debounced: string;
}

/** Debounced semantic memory recall for the palette's Memories section. */
export function useMemorySearch(query: string): MemorySearchResult {
  const { isAuthenticated, userEmail } = useAuth();
  const [debounced, setDebounced] = useState("");

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(query.trim()), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query]);

  const { data, isFetching } = useQuery({
    queryKey: ["command-k", "memory-search", userEmail, debounced],
    queryFn: () => memoryApi.searchMemories(debounced),
    enabled: isAuthenticated && debounced.length >= MIN_CHARS,
    staleTime: 30_000,
  });

  return { memories: data?.memories ?? [], isFetching, debounced };
}

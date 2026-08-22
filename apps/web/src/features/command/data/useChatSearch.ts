"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useAuth } from "@/features/auth/hooks/useAuth";
import {
  type ComprehensiveSearchResponse,
  searchApi,
} from "@/features/search/api/searchApi";

const DEBOUNCE_MS = 250;
const MIN_CHARS = 2;

/** Debounced server-side search over conversations + messages. */
export function useChatSearch(
  query: string,
): ComprehensiveSearchResponse | undefined {
  const { isAuthenticated, userEmail } = useAuth();
  const [debounced, setDebounced] = useState("");

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(query.trim()), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query]);

  const { data } = useQuery({
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

  return data;
}

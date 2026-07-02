"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useAuth } from "@/features/auth/hooks/useAuth";
import {
  type ComprehensiveSearchResponse,
  searchApi,
} from "@/features/search/api/searchApi";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";

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
      const result = await searchApi.search(debounced);
      trackEvent(ANALYTICS_EVENTS.SEARCH_PERFORMED, {
        query_length: debounced.length,
        result_count:
          result.conversations.length +
          result.messages.length +
          result.notes.length,
      });
      return result;
    },
    enabled: isAuthenticated && debounced.length >= MIN_CHARS,
    staleTime: 30_000,
  });

  return data;
}

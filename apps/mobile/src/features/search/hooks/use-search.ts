import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import type { SearchResponse } from "../api/search-api";
import { search } from "../api/search-api";

const SEARCH_DEBOUNCE_MS = 300;
const MIN_QUERY_LENGTH = 2;

export const searchKeys = {
  all: ["search"] as const,
  results: (query: string) => [...searchKeys.all, "results", query] as const,
};

export interface UseSearchReturn {
  query: string;
  setQuery: (q: string) => void;
  debouncedQuery: string;
  results: SearchResponse | undefined;
  isLoading: boolean;
  isDebouncing: boolean;
  error: Error | null;
}

export function useSearch(): UseSearchReturn {
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [isDebouncing, setIsDebouncing] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
    }

    if (query.length >= MIN_QUERY_LENGTH) {
      setIsDebouncing(true);
      timerRef.current = setTimeout(() => {
        setDebouncedQuery(query);
        setIsDebouncing(false);
      }, SEARCH_DEBOUNCE_MS);
    } else {
      setDebouncedQuery("");
      setIsDebouncing(false);
    }

    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
    };
  }, [query]);

  const { data, isLoading, error } = useQuery({
    queryKey: searchKeys.results(debouncedQuery),
    queryFn: () => search(debouncedQuery),
    enabled: debouncedQuery.length >= MIN_QUERY_LENGTH,
    staleTime: 30 * 1000,
  });

  return {
    query,
    setQuery,
    debouncedQuery,
    results: data,
    isLoading: isLoading && debouncedQuery.length >= MIN_QUERY_LENGTH,
    isDebouncing,
    error: error as Error | null,
  };
}

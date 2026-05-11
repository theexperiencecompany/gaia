"use client";

import { useEffect, useState } from "react";

// Module-level cache: one MediaQueryList and one set of subscribers per query
// string. This ensures only a single native listener exists regardless of how
// many components call useMediaQuery with the same query (Rule 4.1).
interface QueryEntry {
  mql: MediaQueryList;
  subscribers: Set<(matches: boolean) => void>;
  listener: (e: MediaQueryListEvent) => void;
}

const queryCache = new Map<string, QueryEntry>();

function subscribeToQuery(
  query: string,
  callback: (matches: boolean) => void,
): () => void {
  if (typeof window === "undefined") return () => {};

  let entry = queryCache.get(query);
  if (!entry) {
    const mql = window.matchMedia(query);
    const subscribers = new Set<(matches: boolean) => void>();
    const listener = (e: MediaQueryListEvent) => {
      for (const cb of subscribers) cb(e.matches);
    };
    mql.addEventListener("change", listener);
    entry = { mql, subscribers, listener };
    queryCache.set(query, entry);
  }

  entry.subscribers.add(callback);

  return () => {
    const current = queryCache.get(query);
    if (!current) return;
    current.subscribers.delete(callback);
    if (current.subscribers.size === 0) {
      current.mql.removeEventListener("change", current.listener);
      queryCache.delete(query);
    }
  };
}

const useMediaQuery = (query: string): boolean => {
  const [matches, setMatches] = useState<boolean>(() =>
    typeof window !== "undefined" ? window.matchMedia(query).matches : false,
  );

  useEffect(() => {
    // Sync immediately in case the query result changed between SSR and mount
    setMatches(window.matchMedia(query).matches);
    return subscribeToQuery(query, setMatches);
  }, [query]);

  return matches;
};

export default useMediaQuery;

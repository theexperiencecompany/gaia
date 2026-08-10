"use client";

import { useCallback, useSyncExternalStore } from "react";

// Module-level cache: one MediaQueryList and one set of subscribers per query
// string. This ensures only a single native listener exists regardless of how
// many components call useMediaQuery with the same query (Rule 4.1).
interface QueryEntry {
  mql: MediaQueryList;
  subscribers: Set<() => void>;
  listener: () => void;
}

const queryCache = new Map<string, QueryEntry>();

function subscribeToQuery(query: string, callback: () => void): () => void {
  if (typeof window === "undefined") {
    return () => {
      /* SSR: no subscription to tear down */
    };
  }

  let entry = queryCache.get(query);
  if (!entry) {
    const mql = window.matchMedia(query);
    const subscribers = new Set<() => void>();
    const listener = () => {
      for (const cb of subscribers) cb();
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

// The server (and the first, hydrating client render) always sees `false`.
// useSyncExternalStore uses this for both SSR and hydration, so the server
// render and the first client render always agree; the real viewport result is
// applied only after hydration completes. This prevents React hydration
// mismatches (error #418) on SSR pages that branch their markup on this hook.
const getServerSnapshot = (): boolean => false;

const useMediaQuery = (query: string): boolean => {
  const subscribe = useCallback(
    (callback: () => void) => subscribeToQuery(query, callback),
    [query],
  );

  const getSnapshot = useCallback(
    () =>
      typeof window !== "undefined" ? window.matchMedia(query).matches : false,
    [query],
  );

  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
};

export default useMediaQuery;

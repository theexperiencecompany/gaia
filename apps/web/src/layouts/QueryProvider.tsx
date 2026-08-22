"use client";

import { QueryClient } from "@tanstack/react-query";
import {
  type PersistedClient,
  type Persister,
  PersistQueryClientProvider,
} from "@tanstack/react-query-persist-client";
import { del, get, set } from "idb-keyval";
import { type ReactNode, useState } from "react";

/**
 * Creates an IndexedDB persister that degrades to a no-op when IndexedDB
 * cannot be opened. iOS Safari refuses to open it under private browsing,
 * storage pressure, or the long-standing WebKit bug, throwing
 * `DOMException: UnknownError: Unable to open database file on disk`. Rather
 * than let every persist tick reject as an uncaught promise, the first failure
 * disables persistence for the session — the query cache still works from
 * memory, only cross-reload restoration is lost.
 * @see https://developer.mozilla.org/en-US/docs/Web/API/IndexedDB_API
 */
export function createIDBPersister(
  idbValidKey: IDBValidKey = "reactQuery",
): Persister {
  let disabled = false;
  const run = async <T,>(
    operation: () => Promise<T>,
  ): Promise<T | undefined> => {
    if (disabled) return undefined;
    try {
      return await operation();
    } catch (error) {
      disabled = true;
      console.error(
        "IndexedDB unavailable — query cache will not persist this session:",
        error,
      );
      return undefined;
    }
  };

  return {
    persistClient: async (client: PersistedClient) => {
      await run(() => set(idbValidKey, client));
    },
    restoreClient: async () => {
      return run(() => get<PersistedClient>(idbValidKey));
    },
    removeClient: async () => {
      await run(() => del(idbValidKey));
    },
  };
}

export default function QueryProvider({ children }: { children: ReactNode }) {
  // Create a client instance
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // With SSR, we usually want to set some default staleTime
            // above 0 to avoid refetching immediately on the client
            staleTime: 60 * 1000, // 1 minute (default for most queries)
            retry: 2,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  // Setup indexedDB for storage of cached queries. Created once so the
  // persister's disabled latch survives re-renders — a fresh persister per
  // render would reset it and retry IndexedDB after the first failure.
  const [persister] = useState(() => createIDBPersister());

  return (
    <PersistQueryClientProvider
      client={queryClient}
      persistOptions={{
        persister,
        maxAge: 30 * 24 * 60 * 60 * 1000, // Maximum age of persisted data (30 days)
        dehydrateOptions: {
          shouldDehydrateQuery: (query) => {
            // Persist successful queries that we want to cache across page reloads
            if (query.state.status !== "success") return false;

            const queryKey = query.queryKey[0];
            return [
              "url-metadata",
              "tools",
              "unread-emails",
              "upcoming-events",
            ].includes(`${queryKey}`);
          },
        },
      }}
    >
      {children}
    </PersistQueryClientProvider>
  );
}

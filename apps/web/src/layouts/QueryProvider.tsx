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
 * Creates an Indexed DB persister
 * @see https://developer.mozilla.org/en-US/docs/Web/API/IndexedDB_API
 */
export function createIDBPersister(idbValidKey: IDBValidKey = "reactQuery") {
  return {
    persistClient: async (client: PersistedClient) => {
      await set(idbValidKey, client);
    },
    restoreClient: async () => {
      return await get<PersistedClient>(idbValidKey);
    },
    removeClient: async () => {
      await del(idbValidKey);
    },
  } satisfies Persister;
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

  // Setup indexedDB for storage of cached queries
  const persister = createIDBPersister();

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
              // "tools",
              // "integrations",
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

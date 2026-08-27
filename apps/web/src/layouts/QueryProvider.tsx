"use client";

import { QueryClient } from "@tanstack/react-query";
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { type ReactNode, useState } from "react";
import { createIDBPersister } from "./queryPersister";

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

"use client";

import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { type ReactNode, useState } from "react";
import { getQueryClient } from "@/lib/queryClient";
import { createIDBPersister, shouldPersistQuery } from "./queryPersister";

export default function QueryProvider({ children }: { children: ReactNode }) {
  const [queryClient] = useState(getQueryClient);

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
          shouldDehydrateQuery: shouldPersistQuery,
        },
      }}
    >
      {children}
    </PersistQueryClientProvider>
  );
}

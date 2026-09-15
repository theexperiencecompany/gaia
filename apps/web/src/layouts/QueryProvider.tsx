"use client";

import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { type ReactNode, useState } from "react";
import { CURRENT_USER_QUERY_KEY } from "@/features/auth/hooks/useCurrentUser";
import { getQueryClient } from "@/lib/queryClient";
import { createIDBPersister } from "./queryPersister";

/**
 * How long a persisted `["current-user"]` entry may be replayed on reload. It
 * is what gives the app its first paint (name, avatar, plan) before
 * `GET /user/me` answers, so it is deliberately shorter than the 30-day
 * default for the rest of the cache — a stale identity is worse than a
 * skeleton. The payload is the profile only: id, name, email, picture,
 * timezone, onboarding, selected model. No tokens, no secrets.
 */
const CURRENT_USER_MAX_AGE_MS = 24 * 60 * 60 * 1000;

const PERSISTED_QUERY_KEYS = [
  "url-metadata",
  "tools",
  "unread-emails",
  "upcoming-events",
];

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
          shouldDehydrateQuery: (query) => {
            // Persist successful queries that we want to cache across page reloads
            if (query.state.status !== "success") return false;

            const queryKey = `${query.queryKey[0]}`;

            // The user is persisted so the shell paints signed-in on reload,
            // but only while it is fresh enough to still be true.
            if (queryKey === CURRENT_USER_QUERY_KEY[0]) {
              return (
                Date.now() - query.state.dataUpdatedAt < CURRENT_USER_MAX_AGE_MS
              );
            }

            return PERSISTED_QUERY_KEYS.includes(queryKey);
          },
        },
      }}
    >
      {children}
    </PersistQueryClientProvider>
  );
}

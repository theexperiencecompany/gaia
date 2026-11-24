import type { UserSubscriptionStatus } from "@shared/api/generated";
import type { Query } from "@tanstack/react-query";
import type {
  PersistedClient,
  Persister,
} from "@tanstack/react-query-persist-client";
import { del, get, set } from "idb-keyval";
import { CURRENT_USER_QUERY_KEY } from "@/features/auth/hooks/useCurrentUser";
import { SUBSCRIPTION_STATUS_QUERY_KEY } from "@/features/pricing/api/queries";

/**
 * How long the persisted session reads (who the user is, that they are on Pro)
 * may be replayed on reload. They give the app its first paint before the API
 * answers, so they expire far sooner than the 30-day default: a stale identity
 * or plan is worse than a spinner. Profile and plan fields only, no tokens.
 */
const SESSION_READ_MAX_AGE_MS = 24 * 60 * 60 * 1000;

const PERSISTED_QUERY_KEYS = [
  "url-metadata",
  "tools",
  "unread-emails",
  "upcoming-events",
];

/** Only a paid plan is replayed: an unpaid one must be re-read, or a new subscriber reloads into the paywall. */
function isSessionRead(queryKey: string, data: unknown): boolean {
  if (queryKey === CURRENT_USER_QUERY_KEY[0]) return true;
  if (queryKey !== SUBSCRIPTION_STATUS_QUERY_KEY[0]) return false;
  return (data as UserSubscriptionStatus | undefined)?.plan_type === "pro";
}

/** Whether a query's data is written to IndexedDB and replayed on the next load. */
export function shouldPersistQuery(query: Query): boolean {
  if (query.state.status !== "success") return false;
  const queryKey = `${query.queryKey[0]}`;
  if (isSessionRead(queryKey, query.state.data)) {
    return Date.now() - query.state.dataUpdatedAt < SESSION_READ_MAX_AGE_MS;
  }
  return PERSISTED_QUERY_KEYS.includes(queryKey);
}

/**
 * Creates an IndexedDB persister that degrades to a no-op when IndexedDB
 * can't open — iOS Safari refuses it under private browsing, storage
 * pressure, or a long-standing WebKit bug (`UnknownError: Unable to open
 * database file on disk`). The first failure disables persistence for the
 * session; the query cache still works from memory, only cross-reload restoration is lost.
 */
export function createIDBPersister(
  idbValidKey: IDBValidKey = "reactQuery",
): Persister {
  let disabled = false;
  const run = async <T>(
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

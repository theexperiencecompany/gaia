import type {
  PersistedClient,
  Persister,
} from "@tanstack/react-query-persist-client";
import { del, get, set } from "idb-keyval";

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

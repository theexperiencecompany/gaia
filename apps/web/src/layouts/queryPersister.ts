import type {
  PersistedClient,
  Persister,
} from "@tanstack/react-query-persist-client";
import { del, get, set } from "idb-keyval";

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

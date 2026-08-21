/**
 * Regression tests for the React Query IndexedDB persister's failure latch.
 *
 * iOS Safari refuses to open IndexedDB under private browsing / storage
 * pressure, so `createIDBPersister` disables persistence for the whole session
 * after the FIRST failure. Untested, that latch is one `disabled = true` away
 * from either never engaging (every persist tick rejects as an uncaught
 * promise) or engaging spuriously. These pin both halves: the first failure
 * degrades, and nothing afterwards touches `idb-keyval` again.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const del = vi.fn();
const get = vi.fn();
const set = vi.fn();

vi.mock("idb-keyval", () => ({
  del: (...args: unknown[]) => del(...args),
  get: (...args: unknown[]) => get(...args),
  set: (...args: unknown[]) => set(...args),
}));

import { createIDBPersister } from "@/layouts/QueryProvider";

const CLIENT = {
  buster: "",
  timestamp: 0,
  clientState: { mutations: [], queries: [] },
};

describe("createIDBPersister", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    del.mockResolvedValue(undefined);
    get.mockResolvedValue(CLIENT);
    set.mockResolvedValue(undefined);
  });

  it("persists and restores through idb-keyval while IndexedDB works", async () => {
    const persister = createIDBPersister();

    await persister.persistClient(CLIENT);
    const restored = await persister.restoreClient();

    expect(set).toHaveBeenCalledWith("reactQuery", CLIENT);
    expect(restored).toBe(CLIENT);
  });

  it("stops touching idb-keyval for the session after a failed set", async () => {
    set.mockRejectedValueOnce(
      new Error("Unable to open database file on disk"),
    );
    const persister = createIDBPersister();

    await persister.persistClient(CLIENT);
    expect(console.error).toHaveBeenCalled();

    await persister.persistClient(CLIENT);
    await persister.removeClient();
    expect(await persister.restoreClient()).toBeUndefined();

    expect(set).toHaveBeenCalledTimes(1);
    expect(del).not.toHaveBeenCalled();
    expect(get).not.toHaveBeenCalled();
  });

  it("stops touching idb-keyval for the session after a failed get", async () => {
    get.mockRejectedValueOnce(new Error("UnknownError"));
    const persister = createIDBPersister();

    expect(await persister.restoreClient()).toBeUndefined();

    await persister.persistClient(CLIENT);
    expect(await persister.restoreClient()).toBeUndefined();

    expect(get).toHaveBeenCalledTimes(1);
    expect(set).not.toHaveBeenCalled();
  });

  it("stops touching idb-keyval for the session after a failed del", async () => {
    del.mockRejectedValueOnce(new Error("UnknownError"));
    const persister = createIDBPersister();

    await persister.removeClient();
    await persister.persistClient(CLIENT);

    expect(del).toHaveBeenCalledTimes(1);
    expect(set).not.toHaveBeenCalled();
  });

  it("keeps each persister's latch to itself", async () => {
    set.mockRejectedValueOnce(new Error("UnknownError"));
    const broken = createIDBPersister();
    await broken.persistClient(CLIENT);

    const fresh = createIDBPersister("otherKey");
    await fresh.persistClient(CLIENT);

    expect(set).toHaveBeenLastCalledWith("otherKey", CLIENT);
  });
});

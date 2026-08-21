/**
 * Regression tests for the chat store's IndexedDB failure latch.
 *
 * iOS Safari refuses to open IndexedDB under private browsing / storage
 * pressure, and a transaction can still fail after a successful open. `ChatDexie`
 * answers both by latching the whole session to unavailable and returning each
 * method's documented fallback instead of leaking an uncaught rejection. These
 * pin that: once latched, no Dexie table is touched again.
 *
 * Dexie itself is mocked — the subject is the wrapper's gate, not IndexedDB
 * (which does not exist in the `node` test environment anyway).
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const conversations = {
  get: vi.fn(),
  put: vi.fn(),
  orderBy: vi.fn(),
};
const messages = {
  get: vi.fn(),
  put: vi.fn(),
  where: vi.fn(),
};
const open = vi.fn();

vi.mock("dexie", () => {
  class FakeDexie {
    open = open;
    version() {
      return { stores: () => undefined };
    }
    table(name: string) {
      return name === "conversations" ? conversations : messages;
    }
  }
  return { default: FakeDexie };
});

/** Fresh module instance so each test gets an unprobed `usable` latch. */
async function loadDb() {
  vi.resetModules();
  return (await import("@/lib/db/chatDb")).db;
}

describe("ChatDexie IndexedDB availability latch", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    open.mockResolvedValue(undefined);
    conversations.orderBy.mockReturnValue({
      reverse: () => ({ toArray: () => Promise.resolve([]) }),
    });
  });

  it("reads through to Dexie while IndexedDB is usable", async () => {
    const stored = { id: "c1", title: "Hi" };
    conversations.get.mockResolvedValue(stored);

    const db = await loadDb();

    expect(await db.getConversation("c1")).toBe(stored);
    expect(conversations.get).toHaveBeenCalledWith("c1");
  });

  it("returns documented fallbacks and never touches Dexie when the open fails", async () => {
    open.mockRejectedValue(new Error("Unable to open database file on disk"));

    const db = await loadDb();

    expect(await db.getConversation("c1")).toBeUndefined();
    expect(await db.getAllConversations()).toEqual([]);
    expect(await db.putConversation({ id: "c1" } as never)).toBe("c1");

    expect(console.error).toHaveBeenCalled();
    expect(conversations.get).not.toHaveBeenCalled();
    expect(conversations.orderBy).not.toHaveBeenCalled();
    expect(conversations.put).not.toHaveBeenCalled();
  });

  it("probes the open exactly once, not per operation", async () => {
    open.mockRejectedValue(new Error("Unable to open database file on disk"));

    const db = await loadDb();
    await db.getConversation("c1");
    await db.getAllConversations();

    expect(open).toHaveBeenCalledTimes(1);
  });

  it("latches the session when a transaction fails after a successful open", async () => {
    conversations.get.mockRejectedValueOnce(new Error("QuotaExceededError"));

    const db = await loadDb();

    expect(await db.getConversation("c1")).toBeUndefined();
    expect(console.error).toHaveBeenCalled();

    // Latched: later reads short-circuit rather than retrying the store.
    expect(await db.getAllConversations()).toEqual([]);
    expect(await db.getConversation("c2")).toBeUndefined();

    expect(conversations.get).toHaveBeenCalledTimes(1);
    expect(conversations.orderBy).not.toHaveBeenCalled();
  });
});

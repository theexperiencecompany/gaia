import { describe, expect, it } from "vitest";
import {
  createOlderHistoryLoader,
  HISTORY_PAGE_SIZE,
  type HistoryPage,
  oldestSeq,
  withLiveRows,
  withNewestPage,
} from "./history";

interface Row {
  id: string;
  seq?: number;
}

const rows = (from: number, to: number): Row[] =>
  Array.from({ length: to - from + 1 }, (_, i) => ({
    id: `m${from + i}`,
    seq: from + i,
  }));

/** A server holding seqs 1..total that answers before_seq the way the API does. */
const scriptedServer = (total: number) => {
  const calls: Array<{ beforeSeq: number; limit: number }> = [];
  const fetchPage = async (
    beforeSeq: number,
    limit: number,
  ): Promise<HistoryPage<Row>> => {
    calls.push({ beforeSeq, limit });
    const before = rows(1, total).filter((row) => (row.seq ?? 0) < beforeSeq);
    const page = before.slice(-limit);
    return { messages: page, has_more: before.length > page.length };
  };
  return { calls, fetchPage };
};

const clientOver = (
  server: ReturnType<typeof scriptedServer>,
  loaded: Row[],
  hasOlder: boolean,
) => {
  const state = { loaded, hasOlder };
  const load = createOlderHistoryLoader<Row>({
    hasOlder: () => state.hasOlder,
    oldestLoadedSeq: () => oldestSeq(state.loaded),
    fetchPage: server.fetchPage,
    applyPage: (page) => {
      state.loaded = [...page.messages, ...state.loaded];
      state.hasOlder = page.has_more;
    },
  });
  return { state, load };
};

describe("createOlderHistoryLoader", () => {
  it("pages back from the oldest loaded seq until the server has no more", async () => {
    const total = HISTORY_PAGE_SIZE * 2 + 20;
    const server = scriptedServer(total);
    const client = clientOver(server, rows(total - 19, total), true);

    await client.load();
    await client.load();
    await client.load();
    await client.load();

    expect(server.calls.map((call) => call.beforeSeq)).toEqual([
      total - 19,
      total - 19 - HISTORY_PAGE_SIZE,
    ]);
    expect(client.state.loaded.map((row) => row.seq)).toEqual(
      rows(1, total).map((row) => row.seq),
    );
    expect(client.state.hasOlder).toBe(false);
  });

  it("stops after a page that exactly reaches the first message", async () => {
    const server = scriptedServer(HISTORY_PAGE_SIZE + 1);
    const client = clientOver(
      server,
      rows(HISTORY_PAGE_SIZE + 1, HISTORY_PAGE_SIZE + 1),
      true,
    );

    await client.load();
    await client.load();

    expect(server.calls).toEqual([
      { beforeSeq: HISTORY_PAGE_SIZE + 1, limit: HISTORY_PAGE_SIZE },
    ]);
    expect(client.state.loaded).toHaveLength(HISTORY_PAGE_SIZE + 1);
    expect(client.state.hasOlder).toBe(false);
  });

  it("fetches nothing when the conversation has no older messages", async () => {
    const server = scriptedServer(10);
    const client = clientOver(server, rows(1, 10), false);

    await client.load();

    expect(server.calls).toEqual([]);
  });

  it("joins a load already in flight instead of asking twice", async () => {
    const server = scriptedServer(200);
    const client = clientOver(server, rows(151, 200), true);

    await Promise.all([client.load(), client.load()]);

    expect(server.calls).toHaveLength(1);
    expect(client.state.loaded).toHaveLength(100);
  });

  it("can load again after a failed page", async () => {
    const server = scriptedServer(100);
    let fail = true;
    const state = { loaded: rows(51, 100), hasOlder: true };
    const load = createOlderHistoryLoader<Row>({
      hasOlder: () => state.hasOlder,
      oldestLoadedSeq: () => oldestSeq(state.loaded),
      fetchPage: (beforeSeq, limit) => {
        if (fail) return Promise.reject(new Error("offline"));
        return server.fetchPage(beforeSeq, limit);
      },
      applyPage: (page) => {
        state.loaded = [...page.messages, ...state.loaded];
        state.hasOlder = page.has_more;
      },
    });

    await expect(load()).rejects.toThrow("offline");
    fail = false;
    await load();

    expect(state.loaded).toHaveLength(100);
  });
});

describe("oldestSeq", () => {
  it("ignores rows the server has not placed yet", () => {
    expect(oldestSeq([{ seq: 7 }, {}, { seq: 3 }, { seq: 9 }])).toBe(3);
    expect(oldestSeq([{}, { seq: undefined }])).toBeNull();
  });
});

describe("withNewestPage", () => {
  it("keeps the older pages already loaded below a refetched newest page", () => {
    const loaded = rows(1, 60);
    const newest = rows(41, 70);

    expect(withNewestPage(loaded, newest).map((row) => row.seq)).toEqual(
      rows(1, 70).map((row) => row.seq),
    );
  });

  it("takes the newest page as-is when it has no placed message", () => {
    expect(withNewestPage(rows(1, 5), [])).toEqual([]);
  });
});

describe("withLiveRows", () => {
  const idOf = (row: Row) => row.id;

  it("shows a row the history and the live view both hold once, from the live view", () => {
    const saved = [...rows(1, 3), { id: "r4", seq: 4, text: "partial" }];
    const live = [
      { id: "r4", seq: 4, text: "finished" },
      { id: "m5", seq: 5 },
    ];
    const merged = withLiveRows<Row & { text?: string }>(saved, live, idOf);
    expect(merged.map(idOf)).toEqual(["m1", "m2", "m3", "r4", "m5"]);
    expect(merged[3]?.text).toBe("finished");
  });

  it("places a live row by its seq among saved rows, and unplaced live rows last", () => {
    const saved = [
      { id: "m1", seq: 1 },
      { id: "m3", seq: 3 },
    ];
    const live = [
      { id: "draft:a1" },
      { id: "work:t1", seq: 2 },
      { id: "pending:m9" },
    ];
    expect(withLiveRows(saved, live, idOf).map(idOf)).toEqual([
      "m1",
      "work:t1",
      "m3",
      "draft:a1",
      "pending:m9",
    ]);
  });

  it("keeps a saved row cached before seq existed ahead of every placed row", () => {
    const saved = [{ id: "legacy" }, { id: "m2", seq: 2 }];
    expect(withLiveRows(saved, [{ id: "m1", seq: 1 }], idOf).map(idOf)).toEqual(
      ["legacy", "m1", "m2"],
    );
  });

  it("joins an older page loaded across the boundary with the newest page and the live view", () => {
    const loaded = withNewestPage(rows(1, 4), rows(5, 8));
    const live = [...rows(7, 9)];
    expect(withLiveRows(loaded, live, idOf).map(idOf)).toEqual(
      rows(1, 9).map(idOf),
    );
  });
});

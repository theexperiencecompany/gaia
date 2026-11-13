import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  type ConversationPage,
  createOlderHistoryLoader,
  HISTORY_PAGE_SIZE,
  hydrate,
  olderBefore,
} from "./history";
import { loadingRow, visibleBubbles } from "./selectors";
import {
  entryFrame,
  generateConversation,
  liveTask,
  reply,
  replyDelta,
  replySettled,
  seededRandom,
  stateFrame,
  toolCallCard,
  userMessage,
  workFinished,
  workStarted,
} from "./testing";
import type {
  ConversationFrame,
  ConversationView,
  Entry,
  LoggedEntry,
  StateFrame,
} from "./types";
import { applyFrame, EMPTY_CONVERSATION_VIEW } from "./view";

const AT = "2026-11-12T10:00:00+00:00";
const IDLE: StateFrame = { kind: "state", head: 0, display: "idle", work: [] };

const fold = (
  frames: readonly ConversationFrame[],
  view = EMPTY_CONVERSATION_VIEW,
): ConversationView =>
  frames.reduce((current, frame) => applyFrame(current, frame).view, view);

/** What the chat screen renders: its rows and its loading row. */
const rendered = (view: ConversationView) => ({
  rows: visibleBubbles(view),
  loading: loadingRow(view),
});

const logged = (entries: Entry[], from = 1): LoggedEntry[] =>
  entries.map((entry, at) => ({ seq: from + at, at: AT, entry }));

const page = (
  entries: LoggedEntry[],
  state: StateFrame,
  cursor: number | null = null,
): ConversationPage => ({
  entries,
  state,
  has_older: cursor !== null,
  cursor,
});

const isLogFrame = (frame: ConversationFrame) =>
  frame.kind === "entry" ||
  frame.kind === "entry_updated" ||
  frame.kind === "state";

/** The page a load at frame cut returns: the log's entries and state as the server held them then. */
function pageAt(frames: readonly ConversationFrame[], cut: number) {
  const before = frames.slice(0, cut);
  const log = fold(before.filter(isLogFrame));
  const state = before.findLast((frame) => frame.kind === "state");
  return page(
    [...log.entries],
    state?.kind === "state" ? state : { ...IDLE, head: log.head },
  );
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-12T10:00:00.000Z"));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("hydrate from history, then the stream", () => {
  it.each(Array.from({ length: 200 }, (_, index) => index + 1))(
    "seed %i: a reload at any frame renders what an all-live session of the same log renders",
    (seed) => {
      const { frames } = generateConversation(seed);
      const cut = Math.floor(seededRandom(seed * 31)() * (frames.length + 1));
      // A resumed stream replays what it still holds of open attempts: their deltas and retracts.
      const streamed = frames
        .slice(0, cut)
        .filter((frame) => !isLogFrame(frame));
      const reloaded = fold(
        [...streamed, ...frames.slice(cut)],
        hydrate(EMPTY_CONVERSATION_VIEW, pageAt(frames, cut)),
      );
      expect(rendered(reloaded)).toEqual(rendered(fold(frames)));
    },
  );

  it("is idempotent with frames the view already applied", () => {
    const { frames } = generateConversation(7);
    const live = fold(frames);
    const again = hydrate(live, pageAt(frames, frames.length));
    expect(rendered(again)).toEqual(rendered(live));
    expect(again.entries).toEqual(live.entries);
  });

  it("never lets a page's older revision undo a newer one the stream applied", () => {
    const live = fold([
      entryFrame(1, userMessage("u1")),
      entryFrame(2, reply("r1", "a1", "final text", 2)),
    ]);
    const stale = page(
      logged([userMessage("u1"), reply("r1", "a1", "first words", 1)]),
      { ...IDLE, head: 2 },
    );
    const [, replyRow] = visibleBubbles(hydrate(live, stale));
    expect(replyRow).toMatchObject({ kind: "reply", text: "final text" });
  });

  it("keeps finished work at its WorkStarted seq across a reload", () => {
    const card = toolCallCard("c1", "sent");
    const frames = [
      entryFrame(1, userMessage("u1")),
      entryFrame(2, workStarted("t1", 1)),
      entryFrame(3, userMessage("u2")),
      entryFrame(4, workFinished("t1", "done", [card])),
      stateFrame(4, "idle"),
    ];
    const order = (view: ConversationView) =>
      visibleBubbles(view).map((row) => row.key);

    const reloaded = hydrate(
      EMPTY_CONVERSATION_VIEW,
      pageAt(frames, frames.length),
    );

    expect(order(reloaded)).toEqual(["user:u1", "work:t1", "user:u2"]);
    expect(order(reloaded)).toEqual(order(fold(frames)));
  });

  it("shows no stray work row once the reply narrating the work has settled", () => {
    const frames = [
      entryFrame(1, userMessage("u1")),
      entryFrame(2, workStarted("t1", 1)),
      entryFrame(3, workFinished("t1", "done", [toolCallCard("c1", "sent")])),
      entryFrame(4, reply("t1", "a1", "sent it")),
      entryFrame(5, replySettled("t1", ["u1"], 1)),
      stateFrame(5, "idle"),
    ];

    const rows = visibleBubbles(
      hydrate(EMPTY_CONVERSATION_VIEW, pageAt(frames, frames.length)),
    );

    expect(rows.map((row) => row.kind)).toEqual(["user", "reply"]);
  });

  it("resumes a reload mid-reply: the open reply streams on and settles in place", () => {
    const open = [
      entryFrame(1, userMessage("u1")),
      stateFrame(1, "thinking"),
      replyDelta("a1", null, 0, "Hel"),
      entryFrame(2, reply("r1", "a1")),
    ];
    const rest = [
      replyDelta("a1", "r1", 1, "lo"),
      entryFrame(3, replySettled("r1", ["u1"], 1)),
      stateFrame(3, "idle"),
    ];
    const reloaded = hydrate(
      EMPTY_CONVERSATION_VIEW,
      pageAt(open, open.length),
    );

    expect(loadingRow(reloaded)).toMatchObject({
      visible: true,
      status: "thinking",
    });
    const streamed = fold(
      [replyDelta("a1", null, 0, "Hel"), ...rest],
      reloaded,
    );
    expect(rendered(streamed)).toEqual(rendered(fold([...open, ...rest])));
  });

  it("shows live work and its approval from the page's state, with no replay", () => {
    const loaded = hydrate(
      EMPTY_CONVERSATION_VIEW,
      page(logged([userMessage("u1"), workStarted("t1", 1)]), {
        kind: "state",
        head: 2,
        display: "awaiting_approval",
        work: [liveTask("t1", true)],
      }),
    );

    expect(loadingRow(loaded).status).toBe("awaiting_approval");
    expect(visibleBubbles(loaded).at(-1)).toMatchObject({
      kind: "work",
      status: "awaiting_approval",
    });
  });
});

describe("loading older pages", () => {
  const log = logged([
    userMessage("u1"),
    reply("r1", "a1", "one"),
    replySettled("r1", ["u1"], 1),
    userMessage("u2"),
    reply("r2", "a2", "two"),
    userMessage("u3"),
    replySettled("r2", ["u2"], 4),
  ]);
  const head: StateFrame = { ...IDLE, head: log.length };

  it("prepends across a boundary the server never cuts inside a reply, rendering the whole log", () => {
    // The newest page reaches back to r2's Reply (seq 5) because it holds r2's settle.
    const newest = page(log.slice(4), head, 5);
    const older = page(log.slice(0, 4), head);

    const view = hydrate(hydrate(EMPTY_CONVERSATION_VIEW, newest), older);

    expect(rendered(view)).toEqual(
      rendered(hydrate(EMPTY_CONVERSATION_VIEW, page(log, head))),
    );
    expect(
      visibleBubbles(hydrate(EMPTY_CONVERSATION_VIEW, newest))[0],
    ).toMatchObject({
      kind: "reply",
      replyId: "r2",
      text: "two",
    });
  });

  it("reads the next older page before the oldest held seq, and stops at the first", () => {
    const newest = page(log.slice(4), head, 5);
    const loaded = hydrate(EMPTY_CONVERSATION_VIEW, newest);
    expect(olderBefore(loaded, newest, null)).toBe(5);

    const older = page(log.slice(0, 4), head);
    expect(olderBefore(hydrate(loaded, older), older, 5)).toBeNull();
  });

  it("keeps the cursor of entries held from before a refetched newest page", () => {
    const held = hydrate(EMPTY_CONVERSATION_VIEW, page(log.slice(1), head, 2));
    const newest = page(log.slice(4), head, 5);
    expect(olderBefore(hydrate(held, newest), newest, 2)).toBe(2);
  });
});

/** A server holding seqs 1..total that answers before_seq the way the API does. */
const scriptedServer = (total: number) => {
  const calls: Array<{ beforeSeq: number; limit: number }> = [];
  const all = logged(
    Array.from({ length: total }, (_, at) => userMessage(`u${at + 1}`)),
  );
  const fetchPage = async (beforeSeq: number, limit: number) => {
    calls.push({ beforeSeq, limit });
    const before = all.filter((entry) => entry.seq < beforeSeq);
    const entries = before.slice(-limit);
    const more = before.length > entries.length;
    return page(
      entries,
      { ...IDLE, head: total },
      more ? entries[0].seq : null,
    );
  };
  return { calls, fetchPage };
};

const clientOver = (
  server: ReturnType<typeof scriptedServer>,
  cursor: number | null,
) => {
  let view = EMPTY_CONVERSATION_VIEW;
  let before = cursor;
  const load = createOlderHistoryLoader({
    olderBefore: () => before,
    fetchPage: server.fetchPage,
    applyPage: (next) => {
      view = hydrate(view, next);
      before = olderBefore(view, next, before);
    },
  });
  return { load, seqs: () => view.entries.map((entry) => entry.seq) };
};

describe("createOlderHistoryLoader", () => {
  it("pages back from the cursor until the server has nothing older", async () => {
    const total = HISTORY_PAGE_SIZE * 2 + 10;
    const server = scriptedServer(total);
    const client = clientOver(server, total + 1);

    await client.load();
    await client.load();
    await client.load();
    await client.load();

    expect(server.calls.map((call) => call.beforeSeq)).toEqual([
      total + 1,
      total + 1 - HISTORY_PAGE_SIZE,
      total + 1 - HISTORY_PAGE_SIZE * 2,
    ]);
    expect(client.seqs()).toEqual(
      Array.from({ length: total }, (_, at) => at + 1),
    );
  });

  it("fetches nothing when nothing older exists", async () => {
    const server = scriptedServer(3);
    await clientOver(server, null).load();
    expect(server.calls).toEqual([]);
  });

  it("joins a load already in flight instead of asking twice", async () => {
    const server = scriptedServer(5);
    const client = clientOver(server, 6);
    await Promise.all([client.load(), client.load()]);
    expect(server.calls).toHaveLength(1);
  });

  it("can load again after a failed page", async () => {
    let fail = true;
    const server = scriptedServer(5);
    let before: number | null = 6;
    const load = createOlderHistoryLoader({
      olderBefore: () => before,
      fetchPage: async (beforeSeq, limit) => {
        if (fail) throw new Error("offline");
        return server.fetchPage(beforeSeq, limit);
      },
      applyPage: (next) => {
        before = next.cursor;
      },
    });

    await expect(load()).rejects.toThrow("offline");
    fail = false;
    await load();
    expect(server.calls).toHaveLength(1);
    expect(before).toBeNull();
  });
});

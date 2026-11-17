/**
 * A reply's delivery survives the bot dying at any step: over generated replies,
 * the process is killed before and after every platform call and every cursor
 * write, a new follower starts from the cursor the server kept, and the chat must
 * end showing exactly what an uninterrupted delivery shows.
 *
 * The one step no client can make exact is a send whose platform id never reached
 * the cursor: the message may exist and cannot be addressed. The cursor names
 * that send (a null id), so the property allows at most one extra message then,
 * and none otherwise.
 *
 * The follower, its screen copy and the delivery machine are real; the platform
 * and the server's cursor are in-memory.
 */
import {
  ConversationFollower,
  type DeliveryCursor,
  type FollowSurface,
  REACTION_OUTCOME,
  type StreamingOptions,
} from "@gaia/shared/bots";
import { describe, expect, it } from "vitest";
import {
  insertFrame,
  replyDelta,
  replyItem,
  screenFrame,
  stateFrame,
  updateFrame,
  userItemWith,
} from "../../../../../libs/shared/ts/src/conversation/testing";
import type { ConversationFrame } from "../../../../../libs/shared/ts/src/conversation/types";

const EDITING: StreamingOptions = {
  editIntervalMs: 0,
  bubblePauseMs: 0,
  streaming: true,
  platform: "telegram",
};
const NON_EDITING: StreamingOptions = {
  editIntervalMs: 0,
  bubblePauseMs: 0,
  streaming: false,
  platform: "whatsapp",
};

const FLOOR = 1;
const REPLY_SEQ = 2;
const WORDS = ["Sure", "the", "flight", "lands", "at", "nine", "tonight"];

/** A small deterministic PRNG (mulberry32), so a failing case replays from its seed. */
function rng(seed: number): () => number {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** A reply of one to four bubbles, each streamed in one to three chunks. */
function generateReply(random: () => number): string[][] {
  const pick = (n: number) => Math.floor(random() * n);
  return Array.from({ length: 1 + pick(4) }, (_, bubble) =>
    Array.from(
      { length: 1 + pick(3) },
      (_, chunk) =>
        `${chunk === 0 ? "" : " "}${WORDS[pick(WORDS.length)]}${bubble}${chunk}`,
    ),
  );
}

const inbound = userItemWith("u1", FLOOR, {
  surface: "telegram",
  platform_message_id: "11",
});

/** The frames of the reply streaming and settling: each chunk a delta, a state frame letting each preview run. */
function streamed(chunks: string[][]): ConversationFrame[] {
  const bubbles = chunks.map((parts) => parts.join(""));
  const frames: ConversationFrame[] = [
    screenFrame([inbound]),
    insertFrame(replyItem("r1", REPLY_SEQ, chunks[0][0])),
  ];
  let index = 0;
  chunks.forEach((parts, bubble) => {
    for (const text of parts) {
      frames.push(replyDelta("a1", "r1", index, text, bubble));
      frames.push(stateFrame(REPLY_SEQ - 1, "thinking"));
      index += 1;
    }
  });
  frames.push(
    updateFrame(replyItem("r1", REPLY_SEQ, bubbles, "answered")),
    stateFrame(REPLY_SEQ, "idle"),
  );
  return frames;
}

/** What a follow that opens after the reply settled receives. */
function settledWhileDown(chunks: string[][]): ConversationFrame[] {
  const bubbles = chunks.map((parts) => parts.join(""));
  return [
    screenFrame([inbound, replyItem("r1", REPLY_SEQ, bubbles, "answered")]),
    stateFrame(REPLY_SEQ, "idle"),
  ];
}

class Crash extends Error {
  constructor() {
    super("bot process died");
  }
}

/** Where the process dies: before or after the n-th step (a platform call or a cursor write). */
interface CrashAt {
  step: number;
  after: boolean;
}

/** One chat on the platform plus the server's cursor, shared by the follow that dies and the one that resumes. */
class World {
  private readonly messages = new Map<string, string>();
  private nextId = 1;
  private steps = 0;
  cursor: DeliveryCursor = { delivered_seq: FLOOR, partial_reply: null };
  crash: CrashAt | null = null;

  /** The texts on screen, oldest first. */
  get screen(): string[] {
    return [...this.messages.values()];
  }

  get stepsTaken(): number {
    return this.steps;
  }

  /** Runs one step, dying before or after it when this is the step the crash names. */
  private async step<T>(effect: () => T): Promise<T> {
    this.steps += 1;
    const dies = this.crash?.step === this.steps;
    if (dies && !this.crash?.after) throw new Crash();
    const result = effect();
    if (dies) throw new Crash();
    return result;
  }

  private edit(id: string, text: string): Promise<void> {
    return this.step(() => {
      if (!this.messages.has(id)) throw new Error("message to edit not found");
      this.messages.set(id, text);
    });
  }

  surface(): FollowSurface {
    const notice = async () => undefined;
    return {
      send: (text) =>
        this.step(() => {
          const id = `m${this.nextId++}`;
          this.messages.set(id, text);
          return { id, edit: (updated) => this.edit(id, updated) };
        }),
      reopen: (id) => ({
        id,
        edit: (updated) => this.edit(id, updated),
        delete: () =>
          this.step(() => {
            this.messages.delete(id);
          }),
      }),
      react: async () => REACTION_OUTCOME.ATTACHED,
      startTyping: () => () => undefined,
      sendFile: notice,
      sendNotice: notice,
      windowClosed: async () => false,
      requester: { sendNotice: notice, sendPhoto: notice },
      links: { conversation: "https://gaia.test/c/c1", pricing: "" },
    };
  }

  follower(options: StreamingOptions): ConversationFollower {
    return new ConversationFollower(
      {
        floor: this.cursor.delivered_seq,
        partialReply: this.cursor.partial_reply,
        record: (cursor) =>
          this.step(() => {
            this.cursor = cursor;
          }),
      },
      options,
      this.surface(),
      "c1",
    );
  }
}

async function feed(
  follower: ConversationFollower,
  frames: ConversationFrame[],
): Promise<"done" | "crashed"> {
  try {
    for (const frame of frames) await follower.apply(frame);
    return "done";
  } catch (error) {
    if (error instanceof Crash) return "crashed";
    throw error;
  }
}

/** Whether shown is expected, or expected plus one message (the unconfirmed send, had it gone out). */
function atMostOneExtra(shown: string[], expected: string[]): boolean {
  const same = (a: string[]) => JSON.stringify(a) === JSON.stringify(expected);
  return (
    same(shown) ||
    shown.some((_, at) => same([...shown.slice(0, at), ...shown.slice(at + 1)]))
  );
}

describe.each([
  ["an editing", EDITING],
  ["a non-editing", NON_EDITING],
])("%s bot killed at every step of a reply's delivery", (_family, options) => {
  it("ends with the chat an uninterrupted delivery shows, one unaddressable send aside", async () => {
    for (let seed = 1; seed <= 40; seed += 1) {
      const chunks = generateReply(rng(seed));
      const clean = new World();
      expect(await feed(clean.follower(options), streamed(chunks))).toBe(
        "done",
      );
      const expected = clean.screen;

      for (let step = 1; step <= clean.stepsTaken; step += 1) {
        for (const after of [false, true]) {
          const world = new World();
          world.crash = { step, after };
          const died = await feed(world.follower(options), streamed(chunks));
          world.crash = null;
          const resumedFrom = world.cursor;
          expect(
            await feed(world.follower(options), settledWhileDown(chunks)),
          ).toBe("done");

          const label = `seed ${seed}, ${after ? "after" : "before"} step ${step} (${died})`;
          const unconfirmed =
            resumedFrom.partial_reply?.open_message_ids?.at(-1) === null;
          if (unconfirmed) {
            expect(atMostOneExtra(world.screen, expected), label).toBe(true);
          } else {
            expect(world.screen, label).toEqual(expected);
          }
          expect(world.cursor, label).toEqual({
            delivered_seq: REPLY_SEQ,
            partial_reply: null,
          });
        }
      }
    }
  });
});

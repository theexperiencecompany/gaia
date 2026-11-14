/**
 * The conversation follower: frames from a conversation's events stream in,
 * platform calls out, for each platform family (editing: Telegram and Slack
 * stream into edited messages; non-editing: WhatsApp, iMessage and Discord send
 * each reply once it is final).
 *
 * Everything runs for real (the shared reducer, the delivery state machine, the
 * follower registry); only the platform is a recorder and the events stream a
 * scripted source.
 */
import {
  type ConversationEventSource,
  ConversationFollower,
  ConversationFollowers,
  type FollowSurface,
  REACTION_OUTCOME,
  type StreamingOptions,
} from "@gaia/shared/bots";
import { describe, expect, it } from "vitest";
import {
  approvalDecided,
  approvalRequested,
  entryFrame,
  entryUpdatedFrame,
  liveTask,
  notice,
  replyDelta,
  reply as replyEntry,
  replySettled,
  stateFrame,
  stopRequested,
  userMessage,
  workFinished,
  workStarted,
} from "../../../../../libs/shared/ts/src/conversation/testing";
import type {
  ConversationFrame,
  Entry,
  Reaction,
} from "../../../../../libs/shared/ts/src/conversation/types";

/** One platform call the follower made. */
type Call =
  | { op: "send"; id: string; text: string; replyTo: string | null }
  | { op: "edit"; id: string; text: string }
  | { op: "delete"; id: string }
  | { op: "react"; target: string; emoji: string; replaces: string | null }
  | { op: "typing"; state: "start" | "stop" }
  | { op: "notice"; bubbles: string[] }
  | { op: "file"; path: string };

/** A platform that records every call, editable and deletable like Telegram. */
function recorder(): { surface: FollowSurface; calls: Call[] } {
  const calls: Call[] = [];
  let next = 1;
  const surface: FollowSurface = {
    sendNotice: async (bubbles) => {
      calls.push({ op: "notice", bubbles });
    },
    sendFile: async (file) => {
      calls.push({ op: "file", path: file.path });
    },
    send: async (text, replyTo) => {
      const id = `m${next++}`;
      calls.push({ op: "send", id, text, replyTo });
      return {
        edit: async (updated) => {
          calls.push({ op: "edit", id, text: updated });
        },
        delete: async () => {
          calls.push({ op: "delete", id });
        },
      };
    },
    react: async (target, emoji, replaces) => {
      calls.push({ op: "react", target, emoji, replaces });
      return REACTION_OUTCOME.ATTACHED;
    },
    startTyping: () => {
      calls.push({ op: "typing", state: "start" });
      return () => calls.push({ op: "typing", state: "stop" });
    },
  };
  return { surface, calls };
}

// A zero edit interval previews every chunk at once, so a run is deterministic.
const EDITING: StreamingOptions = {
  editIntervalMs: 0,
  streaming: true,
  platform: "telegram",
};
const NON_EDITING: StreamingOptions = {
  editIntervalMs: 0,
  streaming: false,
  platform: "whatsapp",
};

/** A user's platform message as the log holds it. */
const inbound = (
  id: string,
  platformId: string,
  reaction: Reaction | null = null,
  revision = 0,
) => ({
  ...userMessage(id, `text of ${id}`, reaction, revision),
  surface: "telegram" as const,
  platform_message_id: platformId,
});

const sent = (calls: Call[]) =>
  calls.flatMap((call) =>
    call.op === "send" ? [{ text: call.text, replyTo: call.replyTo }] : [],
  );

/** What is on screen at the end: each message's last text, deleted ones gone. */
function screen(calls: Call[]): string[] {
  const shown = new Map<string, string>();
  for (const call of calls) {
    if (call.op === "send" || call.op === "edit") shown.set(call.id, call.text);
    if (call.op === "delete") shown.delete(call.id);
  }
  return [...shown.values()];
}

async function feed(
  follower: ConversationFollower,
  frames: ConversationFrame[],
): Promise<void> {
  for (const frame of frames) await follower.apply(frame);
}

/** A whole reply: its entry opened, its text streamed, its fill and its settle. */
function answer(
  seq: number,
  replyId: string,
  text: string,
  answers: string[],
  through: number,
  quote: string | null = null,
): ConversationFrame[] {
  const attempt = `a-${replyId}`;
  return [
    entryFrame(seq, replyEntry(replyId, attempt)),
    replyDelta(attempt, replyId, 0, text.slice(0, 4)),
    replyDelta(attempt, replyId, 1, text.slice(4)),
    entryUpdatedFrame(seq, replyEntry(replyId, attempt, text, 1)),
    entryFrame(seq + 1, replySettled(replyId, answers, through, quote)),
  ];
}

describe.each([
  ["editing", EDITING],
  ["non-editing", NON_EDITING],
])("the follower on a %s platform", (_family, options) => {
  it("answers a burst of three messages with one reply and holds none of them", async () => {
    const { surface, calls } = recorder();
    const opened: string[] = [];
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const source: ConversationEventSource = async function* (_ctx, _id, after) {
      opened.push(after);
      await held;
      const frames = [
        entryFrame(1, inbound("u1", "11")),
        entryFrame(2, inbound("u2", "12")),
        entryFrame(3, inbound("u3", "13")),
        stateFrame(3, "thinking"),
        ...answer(4, "r1", "All three, done.", ["u1", "u2", "u3"], 3),
        stateFrame(5, "idle"),
      ];
      for (const frame of frames) yield { streamId: null, frame };
    };
    const followers = new ConversationFollowers(source, options);
    const ctx = { platform: options.platform, platformUserId: "7" };

    // Each post returns at once; the three join one follow.
    followers.follow(ctx, "c1", 1, surface);
    followers.follow(ctx, "c1", 2, surface);
    followers.follow(ctx, "c1", 3, surface);
    release();
    await followers.idle();

    expect(opened).toEqual(["0"]);
    expect(screen(calls)).toEqual(["All three, done."]);
    expect(sent(calls)).toHaveLength(1);
  });

  it("answers a message sent during work while the work keeps running", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(0, options, surface, "c1");
    follower.expect(1);
    await feed(follower, [
      entryFrame(1, inbound("u1", "11")),
      ...answer(2, "r1", "On it now.", ["u1"], 1),
      entryFrame(4, workStarted("t1", 1)),
      stateFrame(4, "working", [liveTask("t1")]),
    ]);
    follower.expect(5);
    await feed(follower, [
      entryFrame(5, inbound("u2", "12")),
      stateFrame(5, "thinking", [liveTask("t1")]),
      ...answer(6, "r2", "It is Tuesday.", ["u2"], 5),
      stateFrame(7, "working", [liveTask("t1")]),
    ]);

    expect(screen(calls)).toEqual(["On it now.", "It is Tuesday."]);
    // The work is still running, so the follow stays to deliver its result.
    expect(follower.finished).toBe(false);
  });

  it("puts the reaction on the user's message before the reply, and replaces it later", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(0, options, surface, "c1");
    follower.expect(1);
    await feed(follower, [
      entryFrame(1, inbound("u1", "11")),
      entryUpdatedFrame(1, inbound("u1", "11", { emoji: "👍", by: "jev" }, 1)),
      ...answer(2, "r1", "Booked it.", ["u1"], 1),
      entryUpdatedFrame(
        1,
        inbound("u1", "11", { emoji: "🎉", by: "chat_model" }, 2),
      ),
      // A replay of the older revision changes nothing.
      entryUpdatedFrame(1, inbound("u1", "11", { emoji: "👍", by: "jev" }, 1)),
    ]);

    const reactions = calls.filter((call) => call.op === "react");
    expect(reactions).toEqual([
      { op: "react", target: "11", emoji: "👍", replaces: null },
      { op: "react", target: "11", emoji: "🎉", replaces: "👍" },
    ]);
    const firstReaction = calls.findIndex((call) => call.op === "react");
    const firstSend = calls.findIndex((call) => call.op === "send");
    expect(firstReaction).toBeLessThan(firstSend);
  });

  it("stops typing and sends nothing more when stopped mid-work", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(0, options, surface, "c1");
    follower.expect(1);
    await feed(follower, [
      entryFrame(1, inbound("u1", "11")),
      stateFrame(1, "thinking"),
      ...answer(2, "r1", "Working on it.", ["u1"], 1),
      entryFrame(4, workStarted("t1", 1)),
      stateFrame(4, "working", [liveTask("t1")]),
      entryFrame(5, stopRequested("s1", 4)),
      entryFrame(6, workFinished("t1", "cancelled")),
      stateFrame(6, "idle"),
    ]);

    expect(screen(calls)).toEqual(["Working on it."]);
    expect(calls.filter((call) => call.op === "typing")).toEqual([
      { op: "typing", state: "start" },
      { op: "typing", state: "stop" },
    ]);
    expect(follower.finished).toBe(true);
  });

  it("keeps typing while work a later message joined runs, and stops when it ends", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(0, options, surface, "c1");
    follower.expect(1);
    await feed(follower, [
      entryFrame(1, inbound("u1", "11")),
      stateFrame(1, "thinking"),
      ...answer(2, "r1", "On it.", ["u1"], 1),
      entryFrame(4, workStarted("t1", 1)),
      stateFrame(4, "working", [liveTask("t1")]),
    ]);
    follower.expect(5);
    await feed(follower, [
      entryFrame(5, inbound("u2", "12")),
      stateFrame(5, "thinking", [liveTask("t1")]),
      entryFrame(6, workStarted("t2", 5, "t1")),
      ...answer(7, "r2", "Added that to the task.", ["u2"], 5),
      stateFrame(8, "working", [liveTask("t1")]),
    ]);
    const typingWhileJoined = calls.filter((call) => call.op === "typing");
    await feed(follower, [
      entryFrame(9, workFinished("t1")),
      stateFrame(9, "thinking"),
      entryFrame(10, replyEntry("t1", "a-t1", "Both done.", 1)),
      entryFrame(11, replySettled("t1", ["u1", "u2"], 9)),
      stateFrame(11, "idle"),
    ]);

    expect(typingWhileJoined).toEqual([{ op: "typing", state: "start" }]);
    expect(calls.filter((call) => call.op === "typing")).toEqual([
      { op: "typing", state: "start" },
      { op: "typing", state: "stop" },
    ]);
    expect(screen(calls).at(-1)).toBe("Both done.");
    expect(follower.finished).toBe(true);
  });

  it("resumes after a dropped connection without sending anything twice", async () => {
    const { surface, calls } = recorder();
    const cursors: string[] = [];
    const first = [
      entryFrame(1, inbound("u1", "11")),
      stateFrame(1, "thinking"),
      ...answer(2, "r1", "First answer.", ["u1"], 1),
    ];
    const source: ConversationEventSource = async function* (_ctx, _id, after) {
      cursors.push(after);
      if (cursors.length === 1) {
        for (const [index, frame] of first.entries()) {
          yield { streamId: `1-${index}`, frame };
        }
        throw new Error("socket hang up");
      }
      // The server resumes after the cursor; a replayed frame must render nothing.
      for (const frame of first.slice(-4)) yield { streamId: "1-9", frame };
      yield { streamId: "2-0", frame: stateFrame(4, "idle") };
    };
    const followers = new ConversationFollowers(source, options);
    followers.follow(
      { platform: options.platform, platformUserId: "7" },
      "c1",
      1,
      surface,
    );
    await followers.idle();

    expect(cursors).toEqual(["0", `1-${first.length - 1}`]);
    expect(sent(calls)).toHaveLength(1);
    expect(screen(calls)).toEqual(["First answer."]);
  });
});

describe("a late result's native quote", () => {
  const lateResult = (streamed: boolean): ConversationFrame[] => {
    const text = "Your flight is booked.";
    return [
      entryFrame(1, inbound("u1", "11")),
      ...answer(2, "r1", "On it.", ["u1"], 1),
      entryFrame(4, workStarted("t1", 1)),
      entryFrame(5, inbound("u2", "12")),
      ...answer(6, "r2", "Sure, noted.", ["u2"], 5),
      entryFrame(8, workFinished("t1")),
      entryFrame(9, replyEntry("t1", "a-t1", "", 0, "u1")),
      ...(streamed ? [replyDelta("a-t1", "t1", 0, text)] : []),
      entryUpdatedFrame(9, replyEntry("t1", "a-t1", text, 1, "u1")),
      entryFrame(10, replySettled("t1", ["u1"], 8, "u1")),
      stateFrame(10, "idle"),
    ];
  };

  it("answers the original request natively on a platform that sends replies once final", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(0, NON_EDITING, surface, "c1");
    follower.expect(1);
    follower.expect(5);
    await feed(follower, lateResult(true));

    expect(sent(calls)).toEqual([
      { text: "On it.", replyTo: null },
      { text: "Sure, noted.", replyTo: null },
      { text: "Your flight is booked.", replyTo: "11" },
    ]);
    expect(follower.finished).toBe(true);
  });

  it("answers it natively on an editing platform when the result arrives whole", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(0, EDITING, surface, "c1");
    follower.expect(1);
    follower.expect(5);
    await feed(follower, lateResult(false));

    expect(sent(calls).at(-1)).toEqual({
      text: "Your flight is booked.",
      replyTo: "11",
    });
  });

  it("quotes it on the first bubble an editing platform streams", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(0, EDITING, surface, "c1");
    follower.expect(1);
    follower.expect(5);
    await feed(follower, lateResult(true));

    expect(screen(calls).at(-1)).toBe("Your flight is booked.");
    expect(sent(calls).at(-1)).toEqual({
      text: "Your flight is booked.",
      replyTo: "11",
    });
  });
});

describe.each([
  ["editing", EDITING],
  ["non-editing", NON_EDITING],
])("a failed reply on a %s platform", (_family, options) => {
  const failed = (
    failure: "model_error" | "step_limit" | "server_restart",
    partial: string,
  ): ConversationFrame[] => [
    entryFrame(1, inbound("u1", "11")),
    stateFrame(1, "thinking"),
    entryFrame(2, replyEntry("r1", "a-r1")),
    ...(partial ? [replyDelta("a-r1", "r1", 0, partial)] : []),
    entryUpdatedFrame(2, replyEntry("r1", "a-r1", partial, 1)),
    entryFrame(3, replySettled("r1", [], 1, null, "failed", failure)),
    stateFrame(3, "idle"),
  ];

  it.each([
    ["model_error", "❌ Something went wrong. Please try again later."],
    ["step_limit", "❌ Something went wrong. Please try again later."],
    ["server_restart", "🔌 Connection interrupted. Please try again."],
  ] as const)("says why for %s", async (failure, line) => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(0, options, surface, "c1");
    follower.expect(1);
    await feed(follower, failed(failure, ""));

    expect(screen(calls)).toEqual([line]);
    expect(follower.finished).toBe(true);
  });

  it("keeps what was said before the failure and adds the failure line", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(0, options, surface, "c1");
    follower.expect(1);
    await feed(follower, failed("model_error", "Let me look"));

    expect(screen(calls)).toEqual([
      "Let me look",
      "❌ Something went wrong. Please try again later.",
    ]);
  });
});

describe("an approval the work waits on", () => {
  const working: ConversationFrame[] = [
    entryFrame(1, inbound("u1", "11")),
    ...answer(2, "r1", "Sending it.", ["u1"], 1),
    entryFrame(4, workStarted("t1", 1)),
    stateFrame(4, "working", [liveTask("t1")]),
  ];

  it("asks once, as a yes/no prompt with its expiry, and not again on replay", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(0, NON_EDITING, surface, "c1");
    follower.expect(1);
    const expiresAt = new Date(Date.now() + 2 * 60 * 60 * 1000).toISOString();
    const asked = entryFrame(
      5,
      approvalRequested("t1", "ap1", "Send email to Sam", expiresAt),
    );
    await feed(follower, [
      ...working,
      asked,
      stateFrame(5, "awaiting_approval", [liveTask("t1", true)]),
      asked,
    ]);

    expect(sent(calls).slice(1)).toEqual([
      {
        text: "*Approval needed:* Send email to Sam\nReply *yes* to approve or *no* to decline. This expires in 2 hours.",
        replyTo: null,
      },
    ]);
    expect(follower.finished).toBe(false);
  });

  it("numbers every approval still open when another one arrives", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(0, NON_EDITING, surface, "c1");
    follower.expect(1);
    await feed(follower, [
      ...working,
      entryFrame(5, approvalRequested("t1", "ap1", "Send email to Sam")),
      entryFrame(6, approvalRequested("t1", "ap2", "Book the 9am flight")),
      entryFrame(7, approvalDecided("ap1")),
      entryFrame(8, approvalRequested("t1", "ap3", "Pay the invoice")),
    ]);

    expect(
      sent(calls)
        .slice(1)
        .map(({ text }) => text),
    ).toEqual([
      "*Approval needed:* Send email to Sam\nReply *yes* to approve or *no* to decline.",
      "*Approvals needed:*\n1. Send email to Sam\n2. Book the 9am flight\nReply *yes* to approve all, *no* to decline all, or say which numbers you mean.",
      "*Approvals needed:*\n1. Book the 9am flight\n2. Pay the invoice\nReply *yes* to approve all, *no* to decline all, or say which numbers you mean.",
    ]);
  });

  it("does not ask for an approval from before the follow", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(5, NON_EDITING, surface, "c1");
    follower.expect(6);
    await feed(follower, [
      ...working,
      entryFrame(5, approvalRequested("t1", "ap1", "Send email to Sam")),
      entryFrame(6, inbound("u2", "12")),
    ]);

    expect(sent(calls)).toEqual([]);
  });
});

describe("a notice and a reply's files", () => {
  const artifact = (path: string) => ({
    tool_name: "artifact_data",
    tool_category: "coding",
    data: {
      event: "upsert",
      session_id: "c1",
      path,
      size_bytes: 10,
      mtime: 1,
      content_type: "application/pdf",
    },
  });

  it.each([
    ["editing", EDITING],
    ["non-editing", NON_EDITING],
  ])(
    "sends a notice logged in an idle conversation once on a %s platform, a replay included",
    async (_family, options) => {
      const { surface, calls } = recorder();
      const follower = new ConversationFollower(3, options, surface, "c1");
      const frames = [
        entryFrame(4, notice("n1", "Your reminder: call the bank")),
        stateFrame(4, "idle"),
      ];
      await feed(follower, frames);
      await feed(follower, frames);

      expect(calls.filter((call) => call.op === "notice")).toEqual([
        { op: "notice", bubbles: ["Your reminder: call the bank"] },
      ]);
      expect(follower.finished).toBe(true);
    },
  );

  it("uploads each file a settled reply wrote once, after its text", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(0, NON_EDITING, surface, "c1");
    follower.expect(1);
    const opened = replyEntry("r1", "a-r1", "Here is the report.");
    if (opened.kind !== "reply") throw new Error("reply() builds a reply");
    const written: Entry = {
      ...opened,
      tool_data: [artifact("out/report.pdf"), artifact("out/report.pdf")],
    };
    await feed(follower, [
      entryFrame(1, inbound("u1", "11")),
      entryFrame(2, written),
      entryFrame(3, replySettled("r1", ["u1"], 1)),
      entryFrame(3, replySettled("r1", ["u1"], 1)),
      stateFrame(3, "idle"),
    ]);

    expect(
      calls.flatMap((call) =>
        call.op === "send" || call.op === "file"
          ? [call.op === "send" ? call.text : call.path]
          : [],
      ),
    ).toEqual(["Here is the report.", "out/report.pdf"]);
  });
});

describe("a follow the server woke", () => {
  it("repeats nothing a follow already delivered when the wake comes late", async () => {
    const { surface, calls } = recorder();
    const frames = [
      entryFrame(1, inbound("u1", "11")),
      stateFrame(1, "thinking"),
      ...answer(2, "r1", "Done.", ["u1"], 1),
      entryFrame(4, notice("n1", "Heads up")),
      stateFrame(4, "idle"),
    ];
    const source: ConversationEventSource = async function* (_ctx, _id, after) {
      for (const frame of frames) {
        if (!("seq" in frame) || frame.seq > Number(after))
          yield { streamId: null, frame };
      }
    };
    const followers = new ConversationFollowers(source, NON_EDITING);
    const ctx = { platform: NON_EDITING.platform, platformUserId: "7" };

    followers.follow(ctx, "c1", 1, surface);
    await followers.idle();
    // The wakes for the reply and the notice, consumed after that follow ended.
    followers.resume(ctx, "c1", 1, surface);
    await followers.idle();
    followers.resume(ctx, "c1", 3, surface);
    await followers.idle();

    expect(screen(calls)).toEqual(["Done."]);
    expect(calls.filter((call) => call.op === "notice")).toHaveLength(1);
  });
});

describe("history the follow started after", () => {
  it("renders nothing for a reply settled before the posted message", async () => {
    const { surface, calls } = recorder();
    // The stream also replays frames from before the floor (seq 3 here).
    const follower = new ConversationFollower(3, EDITING, surface, "c1");
    follower.expect(4);
    await feed(follower, [
      ...answer(2, "old", "An old answer.", ["u0"], 1),
      entryFrame(4, inbound("u1", "11")),
      ...answer(5, "r1", "A new answer.", ["u1"], 4),
      stateFrame(6, "idle"),
    ]);

    expect(screen(calls)).toEqual(["A new answer."]);
    expect(follower.finished).toBe(true);
  });
});

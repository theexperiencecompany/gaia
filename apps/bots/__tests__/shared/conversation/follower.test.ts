/**
 * The conversation follower: the server's screen patches in, platform calls out,
 * for each platform family (editing: Telegram and Slack stream into edited
 * messages; non-editing: WhatsApp, iMessage and Discord send each reply once it
 * is final).
 *
 * Everything runs for real (the shared screen copy, the delivery state machine,
 * the follower registry); only the platform is a recorder and the events stream
 * a scripted source.
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
  approvalAsked,
  founderConversationFrames,
  insertFrame,
  noticeItem,
  replyDelta,
  replyItem,
  screenFrame,
  stateFrame,
  updateFrame,
  userItemWith,
  workItem,
} from "../../../../../libs/shared/ts/src/conversation/testing";
import type {
  ConversationFrame,
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

/** A user's platform message as the server's screen shows it. */
const inbound = (
  id: string,
  seq: number,
  platformId: string,
  reaction: Reaction | null = null,
) =>
  userItemWith(id, seq, {
    surface: "telegram",
    platform_message_id: platformId,
    reaction,
  });

/** A whole reply: its item inserted with its first words, the rest streamed, then settled. */
function answer(
  seq: number,
  replyId: string,
  text: string,
  quoteOf: string | null = null,
): ConversationFrame[] {
  const attempt = `a-${replyId}`;
  const quote = quoteOf
    ? { id: quoteOf, content: "", role: "user" as const }
    : null;
  return [
    insertFrame({ ...replyItem(replyId, seq, text.slice(0, 4)), quote }),
    replyDelta(attempt, replyId, 0, text.slice(0, 4)),
    replyDelta(attempt, replyId, 1, text.slice(4)),
    updateFrame({ ...replyItem(replyId, seq, text, "answered"), quote }),
  ];
}

describe.each([
  ["editing", EDITING],
  ["non-editing", NON_EDITING],
])("the follower on a %s platform", (_family, options) => {
  it("answers a burst of three messages with one reply over one follow", async () => {
    const { surface, calls } = recorder();
    let opened = 0;
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const source: ConversationEventSource = async function* () {
      opened += 1;
      await held;
      yield screenFrame([
        inbound("u1", 1, "11"),
        inbound("u2", 2, "12"),
        inbound("u3", 3, "13"),
      ]);
      yield stateFrame(3, "thinking");
      yield* answer(4, "r1", "All three, done.");
      yield stateFrame(4, "idle");
    };
    const followers = new ConversationFollowers(source, options);
    const ctx = { platform: options.platform, platformUserId: "7" };

    followers.follow(ctx, "c1", 1, surface);
    followers.follow(ctx, "c1", 2, surface);
    followers.follow(ctx, "c1", 3, surface);
    release();
    await followers.idle();

    expect(opened).toBe(1);
    expect(screen(calls)).toEqual(["All three, done."]);
    expect(sent(calls)).toHaveLength(1);
  });

  it("renders the founder's conversation as its one result reply, and nothing twice on a reconnect", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(0, options, surface, "c1");
    const frames = [screenFrame([]), ...founderConversationFrames()];
    await feed(follower, frames);
    const reconnected = follower.apply(
      screenFrame(
        frames.flatMap((frame) =>
          frame.kind === "screen_insert" ? [frame.item] : [],
        ),
      ),
    );
    await reconnected;

    expect(screen(calls)).toEqual(["Buy milk was already on your list."]);
    expect(sent(calls)).toHaveLength(1);
  });

  it("puts the reaction on the user's message, and replaces it later", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(0, options, surface, "c1");
    await feed(follower, [
      screenFrame([inbound("u1", 1, "11")]),
      updateFrame(inbound("u1", 1, "11", { emoji: "👀", by: "jev" })),
      updateFrame(inbound("u1", 1, "11", { emoji: "👍", by: "jev" })),
    ]);

    expect(calls.filter((call) => call.op === "react")).toEqual([
      { op: "react", target: "11", emoji: "👀", replaces: null },
      { op: "react", target: "11", emoji: "👍", replaces: "👀" },
    ]);
  });

  it("answers the quoted message natively", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(0, options, surface, "c1");
    await feed(follower, [
      screenFrame([inbound("u1", 1, "11"), inbound("u2", 2, "12")]),
      ...answer(3, "r1", "About the first one.", "u1"),
    ]);

    expect(sent(calls)[0]).toEqual({
      text: options.streaming ? "Abou" : "About the first one.",
      replyTo: "11",
    });
  });
});

describe("a failed reply", () => {
  it("keeps what was said before the failure and adds the failure line", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(0, NON_EDITING, surface, "c1");
    await feed(follower, [
      screenFrame([inbound("u1", 1, "11")]),
      updateFrame({
        ...replyItem("r1", 2, "Here is the start", "failed"),
        failure: "server_restart",
      }),
    ]);

    expect(sent(calls).map(({ text }) => text)).toEqual([
      "Here is the start",
      "🔌 Connection interrupted. Please try again.",
    ]);
  });
});

describe("an approval the work waits on", () => {
  const asking = (...approvals: ReturnType<typeof approvalAsked>[]) =>
    updateFrame(workItem("t1", 2, "awaiting_approval", approvals));
  const sam = approvalAsked("t1", "ap1", "Send email to Sam");
  const flight = approvalAsked("t1", "ap2", "Book the 9am flight");
  const invoice = approvalAsked("t1", "ap3", "Pay the invoice");

  it("asks once, as a yes/no prompt with its expiry, and not again on a reconnect", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(0, NON_EDITING, surface, "c1");
    follower.expect(1);
    const expiresAt = new Date(Date.now() + 2 * 60 * 60 * 1000).toISOString();
    const expiring = approvalAsked("t1", "ap1", "Send email to Sam", expiresAt);
    await feed(follower, [
      screenFrame([inbound("u1", 1, "11"), workItem("t1", 2, "running")]),
      asking(expiring),
      stateFrame(3, "awaiting_approval"),
      screenFrame([
        inbound("u1", 1, "11"),
        workItem("t1", 2, "awaiting_approval", [expiring]),
      ]),
    ]);

    expect(sent(calls)).toEqual([
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
    await feed(follower, [
      screenFrame([inbound("u1", 1, "11"), workItem("t1", 2, "running")]),
      asking(sam),
      asking(sam, flight),
      asking(flight),
      asking(flight, invoice),
    ]);

    expect(sent(calls).map(({ text }) => text)).toEqual([
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
      screenFrame([
        inbound("u1", 1, "11"),
        workItem("t1", 2, "awaiting_approval", [sam]),
      ]),
      insertFrame(inbound("u2", 6, "12")),
    ]);

    expect(sent(calls)).toEqual([]);
  });
});

describe("history the follow started after", () => {
  it("renders nothing for a reply settled before the posted message", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(2, NON_EDITING, surface, "c1");
    await feed(follower, [
      screenFrame([
        inbound("u1", 1, "11", { emoji: "👍", by: "jev" }),
        replyItem("r1", 2, "Old answer", "answered"),
      ]),
      insertFrame(inbound("u2", 3, "12")),
    ]);

    expect(calls.filter((call) => call.op !== "typing")).toEqual([]);
  });
});

describe("an approval logged after the follow's floor on work started before it", () => {
  it("is asked, once", async () => {
    const { surface, calls } = recorder();
    const sam = approvalAsked("t1", "ap1", "Send email to Sam");
    // Woken for the approval logged at seq 7, on work the screen shows at seq 2.
    const follower = new ConversationFollower(6, NON_EDITING, surface, "c1");
    const asking = workItem("t1", 2, "awaiting_approval", [sam], 7);
    await feed(follower, [
      screenFrame([inbound("u1", 1, "11"), asking]),
      screenFrame([inbound("u1", 1, "11"), asking]),
    ]);

    expect(sent(calls).map(({ text }) => text)).toEqual([
      "*Approval needed:* Send email to Sam\nReply *yes* to approve or *no* to decline.",
    ]);
  });
});

describe("a notice and a reply's files", () => {
  it.each([
    ["editing", EDITING],
    ["non-editing", NON_EDITING],
  ])(
    "sends a notice logged in an idle conversation once on a %s platform, a replay included",
    async (_family, options) => {
      const { surface, calls } = recorder();
      const follower = new ConversationFollower(3, options, surface, "c1");
      const frames = [
        insertFrame(noticeItem("n1", 4, "Your reminder: call the bank")),
        stateFrame(4, "idle"),
      ];
      await feed(follower, frames);
      await feed(follower, [
        screenFrame([noticeItem("n1", 4, "Your reminder: call the bank")]),
      ]);

      expect(calls.filter((call) => call.op === "notice")).toEqual([
        { op: "notice", bubbles: ["Your reminder: call the bank"] },
      ]);
    },
  );

  it("sends no notice from before the follow", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(4, NON_EDITING, surface, "c1");
    await feed(follower, [screenFrame([noticeItem("n1", 4, "Old reminder")])]);

    expect(calls.filter((call) => call.op === "notice")).toEqual([]);
  });

  it("uploads the files a settled reply delivers once, after its text", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(0, NON_EDITING, surface, "c1");
    follower.expect(1);
    const files = [{ path: "out/report.pdf", content_type: "application/pdf" }];
    const settled = {
      ...replyItem("r1", 2, "Here is the report.", "answered"),
      files,
    };
    await feed(follower, [
      insertFrame(inbound("u1", 1, "11")),
      insertFrame({ ...replyItem("r1", 2, "Here is the report."), files }),
      updateFrame(settled),
      updateFrame(settled),
    ]);

    expect(
      calls.flatMap((call) =>
        call.op === "send"
          ? [call.text]
          : call.op === "file"
            ? [call.path]
            : [],
      ),
    ).toEqual(["Here is the report.", "out/report.pdf"]);
  });
});

describe("a follow the server woke", () => {
  it("repeats nothing a follow already delivered when the wake comes late", async () => {
    const { surface, calls } = recorder();
    const frames = [
      screenFrame([]),
      insertFrame(inbound("u1", 1, "11")),
      stateFrame(1, "thinking"),
      ...answer(2, "r1", "Done."),
      insertFrame(noticeItem("n1", 3, "Heads up")),
      stateFrame(3, "idle"),
    ];
    const latest = [
      screenFrame([
        inbound("u1", 1, "11"),
        replyItem("r1", 2, "Done.", "answered"),
        noticeItem("n1", 3, "Heads up"),
      ]),
      stateFrame(3, "idle"),
    ];
    let follows = 0;
    const source: ConversationEventSource = async function* () {
      follows += 1;
      for (const frame of follows === 1 ? frames : latest) yield frame;
    };
    const followers = new ConversationFollowers(source, NON_EDITING);
    const ctx = { platform: NON_EDITING.platform, platformUserId: "7" };

    followers.follow(ctx, "c1", 1, surface);
    await followers.idle();
    // The wakes for the reply and the notice, consumed after that follow ended.
    followers.resume(ctx, "c1", 1, surface);
    await followers.idle();
    followers.resume(ctx, "c1", 2, surface);
    await followers.idle();

    expect(screen(calls)).toEqual(["Done."]);
    expect(calls.filter((call) => call.op === "notice")).toHaveLength(1);
  });
});

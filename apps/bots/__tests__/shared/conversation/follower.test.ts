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
  type DeliveryCursor,
  type DeliveryRecorder,
  type FollowStart,
  type FollowSurface,
  REACTION_OUTCOME,
  StaleScreen,
  type StreamingOptions,
} from "@gaia/shared/bots";
import { describe, expect, it } from "vitest";
import {
  approvalAsked,
  founderConversationFrames,
  groupedTimeline,
  insertFrame,
  noticeItem,
  patchFrame,
  replyDelta,
  replyItem,
  retractFrame,
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
  | { op: "typing"; state: "start"; on: string | null }
  | { op: "typing"; state: "stop" }
  | { op: "notice"; bubbles: string[] }
  | { op: "dm"; bubbles: string[] }
  | { op: "photo"; url: string; caption: string }
  | { op: "file"; path: string };

const CONVERSATION_LINK = "https://gaia.test/c/c1";
const PRICING_LINK = "https://gaia.test/pricing";

/** How the recorded platform behaves: a group chat, a closed message window, refused uploads. */
interface PlatformBehaviour {
  group?: boolean;
  windowClosed?: boolean;
  refusePhoto?: () => Error;
  refuseFile?: () => Error;
}

/** A platform that records every call, editable and deletable like Telegram. */
function recorder(behaviour: PlatformBehaviour = {}): {
  surface: FollowSurface;
  calls: Call[];
} {
  const calls: Call[] = [];
  let next = 1;
  const sendNotice = async (bubbles: string[]) => {
    calls.push({ op: "notice", bubbles });
  };
  const surface: FollowSurface = {
    sendNotice,
    sendPhoto: async (url, caption) => {
      if (behaviour.refusePhoto) throw behaviour.refusePhoto();
      calls.push({ op: "photo", url, caption });
    },
    windowClosed: async () => behaviour.windowClosed ?? false,
    links: { pricing: PRICING_LINK },
    requester: {
      sendNotice: behaviour.group
        ? async (bubbles) => {
            calls.push({ op: "dm", bubbles });
          }
        : sendNotice,
      sendPhoto: async (url, caption) => {
        if (behaviour.refusePhoto) throw behaviour.refusePhoto();
        calls.push({ op: "photo", url, caption });
      },
    },
    sendFile: async (_conversationId, file) => {
      if (behaviour.refuseFile) throw behaviour.refuseFile();
      calls.push({ op: "file", path: file.path });
    },
    send: async (text, replyTo) => {
      const id = `m${next++}`;
      calls.push({ op: "send", id, text, replyTo });
      return {
        id,
        edit: async (updated) => {
          calls.push({ op: "edit", id, text: updated });
        },
      };
    },
    reopen: (id) => ({
      id,
      edit: async (updated) => {
        calls.push({ op: "edit", id, text: updated });
      },
      delete: async () => {
        calls.push({ op: "delete", id });
      },
    }),
    react: async (target, emoji, replaces) => {
      calls.push({ op: "react", target, emoji, replaces });
      return REACTION_OUTCOME.ATTACHED;
    },
    startTyping: (on) => {
      calls.push({ op: "typing", state: "start", on });
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
const SLACK: StreamingOptions = {
  editIntervalMs: 0,
  streaming: true,
  platform: "slack",
};

/** A follow after floor that keeps no cursor. */
const startAfter = (floor: number): FollowStart => ({
  floor,
  partialReply: null,
  record: async () => undefined,
});
const NOT_KEPT: DeliveryRecorder = async () => undefined;
const cursorAt = (seq: number): DeliveryCursor => ({
  delivered_seq: seq,
  partial_reply: null,
});

const sent = (calls: Call[]) =>
  calls.flatMap((call) =>
    call.op === "send" ? [{ text: call.text, replyTo: call.replyTo }] : [],
  );

/** What is on screen at the end: each message's last text. */
function screen(calls: Call[]): string[] {
  const shown = new Map<string, string>();
  for (const call of calls) {
    if (call.op === "send" || call.op === "edit") shown.set(call.id, call.text);
    if (call.op === "delete") shown.delete(call.id);
  }
  return [...shown.values()];
}

/** Every edit that took back text a message already showed. */
function takenBack(calls: Call[]): Call[] {
  const shown = new Map<string, string>();
  return calls.filter((call) => {
    if (call.op === "send") shown.set(call.id, call.text);
    if (call.op !== "edit") return false;
    const before = shown.get(call.id) ?? "";
    shown.set(call.id, call.text);
    return !call.text.startsWith(before);
  });
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
    const followers = new ConversationFollowers(source, options, NOT_KEPT);
    const ctx = { platform: options.platform, platformUserId: "7" };

    followers.follow(ctx, "c1", 1, cursorAt(0), surface);
    followers.follow(ctx, "c1", 2, cursorAt(1), surface);
    followers.follow(ctx, "c1", 3, cursorAt(2), surface);
    release();
    await followers.idle();

    expect(opened).toBe(1);
    expect(screen(calls)).toEqual(["All three, done."]);
    expect(sent(calls)).toHaveLength(1);
  });

  it("renders the founder's conversation as its one result reply, and nothing twice on a reconnect", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(
      startAfter(0),
      options,
      surface,
      "c1",
    );
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
    const follower = new ConversationFollower(
      startAfter(0),
      options,
      surface,
      "c1",
    );
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

  it("posts a reply of three bubbles as the three bubbles it saved", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(startAfter(0), options, surface);
    const bubbles = ["On it.", "Found 3 flights.", "The cheapest is $90."];
    await feed(follower, [
      screenFrame([inbound("u1", 1, "11")]),
      insertFrame(replyItem("r1", 2, ["On"])),
      replyDelta("a-r1", "r1", 0, "On"),
      replyDelta("a-r1", "r1", 1, " it."),
      replyDelta("a-r1", "r1", 2, "Found 3", 1),
      replyDelta("a-r1", "r1", 3, " flights.", 1),
      replyDelta("a-r1", "r1", 4, "The cheapest is $90.", 2),
      updateFrame(replyItem("r1", 2, bubbles, "answered")),
    ]);

    expect(screen(calls)).toEqual(bubbles);
    expect(sent(calls)).toHaveLength(3);
    // Each message only ever grows into its bubble: nothing streamed was taken back.
    expect(takenBack(calls)).toEqual([]);
  });

  it("answers the quoted message natively", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(
      startAfter(0),
      options,
      surface,
      "c1",
    );
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

describe("a hand-off preamble", () => {
  it("stays on screen when its attempt is retried, and the reply follows below it", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(startAfter(0), EDITING, surface);
    await feed(follower, [
      screenFrame([inbound("u1", 1, "11")]),
      insertFrame(replyItem("r1", 2, ["Let me check."])),
      replyDelta("a-r1", "r1", 0, "Let me check."),
      replyDelta("a-r1", "r1", 1, "One sec.", 1),
    ]);
    expect(sent(calls)).toHaveLength(2);

    await follower.apply(retractFrame("a-r1"));
    await follower.apply(
      updateFrame(
        replyItem("r1", 2, ["Let me check.", "One sec.", "Done."], "answered"),
      ),
    );
    expect(screen(calls)).toEqual(["Let me check.", "One sec.", "Done."]);
    expect(takenBack(calls)).toEqual([]);
  });
});

describe("a failed reply", () => {
  it("keeps what was said before the failure and adds the failure line", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(
      startAfter(0),
      NON_EDITING,
      surface,
      "c1",
    );
    await feed(follower, [
      screenFrame([inbound("u1", 1, "11")]),
      updateFrame({
        ...replyItem("r1", 2, "Here is the start", "failed"),
        failure: "model_error",
        failure_line:
          "I couldn't finish that reply. Send your message again to retry.",
      }),
    ]);

    expect(sent(calls).map(({ text }) => text)).toEqual(["Here is the start"]);
    // The server words the line: the platform shows it as it was sent.
    expect(calls.filter((call) => call.op === "notice")).toEqual([
      {
        op: "notice",
        bubbles: [
          "I couldn't finish that reply. Send your message again to retry.",
        ],
      },
    ]);
  });
});

describe("a usage limit the run hit", () => {
  const limitCard = (current_plan: string) => ({
    tool_name: "rate_limit_data",
    data: {
      feature: "daily_budget",
      plan_required: "pro",
      reset_time: null,
      current_plan,
      message: "You've used today's budget.",
    },
  });

  it("follows the reply with the limit and the upgrade link on a free plan", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(
      startAfter(0),
      SLACK,
      surface,
      "c1",
    );
    await feed(follower, [
      screenFrame([inbound("u1", 1, "11")]),
      updateFrame({
        ...replyItem("r1", 2, "", "answered"),
        timeline: groupedTimeline([limitCard("free")]),
      }),
    ]);

    expect(calls.filter((call) => call.op === "notice")).toEqual([
      {
        op: "notice",
        bubbles: [
          `⏳ You've used today's budget. <${PRICING_LINK}|Upgrade to Pro> for higher limits.`,
        ],
      },
    ]);
  });

  it("tells a limit a piece of work hit once, without an upgrade link on Pro", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(
      startAfter(0),
      SLACK,
      surface,
      "c1",
    );
    const limited = {
      ...workItem("t1", 2, "failed"),
      timeline: groupedTimeline([limitCard("pro")]),
    };
    await feed(follower, [
      screenFrame([inbound("u1", 1, "11")]),
      insertFrame(limited),
      updateFrame(limited),
    ]);

    expect(calls.filter((call) => call.op === "notice")).toEqual([
      { op: "notice", bubbles: ["⏳ You've used today's budget."] },
    ]);
  });
});

describe("a reply after the platform's message window closed (WhatsApp's 24 h)", () => {
  it("goes as one notice, the template path, instead of a refused free-form send", async () => {
    const { surface, calls } = recorder({ windowClosed: true });
    const follower = new ConversationFollower(
      startAfter(0),
      NON_EDITING,
      surface,
      "c1",
    );
    await feed(follower, [
      screenFrame([inbound("u1", 1, "11")]),
      updateFrame(replyItem("r1", 2, ["Done.", "Here it is."], "answered")),
    ]);

    expect(sent(calls)).toEqual([]);
    expect(calls.filter((call) => call.op === "notice")).toEqual([
      { op: "notice", bubbles: ["Done.", "Here it is."] },
    ]);
    expect(follower.summary.repliesDelivered).toBe(1);
  });
});

const SAM_EMAIL = {
  action: "Send an email",
  question: "OK to email sam@x.com about \u201cQ3 numbers\u201d?",
  confirm: "send it",
  details: [
    {
      label: "Message",
      value: "\u201cHi Sam, the Q3 numbers are attached.\u201d",
      expandable: true,
    },
  ],
};
const SAM_HEADLINE = "Email sam@x.com about \u201cQ3 numbers\u201d";
const SAM_PROMPT =
  "*OK to email sam@x.com about \u201cQ3 numbers\u201d?*\nMessage: \u201cHi Sam, the Q3 numbers are attached.\u201d\n\nReply *yes* or *no*.";

describe("an approval the work waits on", () => {
  const asking = (...approvals: ReturnType<typeof approvalAsked>[]) =>
    updateFrame(workItem("t1", 2, "awaiting_approval", approvals));
  const sam = approvalAsked("t1", "ap1", SAM_HEADLINE, null, SAM_EMAIL);
  const flight = approvalAsked("t1", "ap2", "Book the 9am flight");
  const invoice = approvalAsked("t1", "ap3", "Pay the invoice");

  it("asks once, as one yes/no question without its expiry, and not again on a reconnect", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(
      startAfter(0),
      NON_EDITING,
      surface,
      "c1",
    );
    follower.expect(1);
    const expiresAt = new Date(Date.now() + 2 * 60 * 60 * 1000).toISOString();
    const expiring = approvalAsked(
      "t1",
      "ap1",
      SAM_HEADLINE,
      expiresAt,
      SAM_EMAIL,
    );
    await feed(follower, [
      screenFrame([inbound("u1", 1, "11"), workItem("t1", 2, "running")]),
      asking(expiring),
      stateFrame(3, "awaiting_approval"),
      screenFrame([
        inbound("u1", 1, "11"),
        workItem("t1", 2, "awaiting_approval", [expiring]),
      ]),
    ]);

    expect(sent(calls)).toEqual([{ text: SAM_PROMPT, replyTo: null }]);
    expect(follower.finished).toBe(false);
  });

  it("names only the new approval, under the number the server gave it", async () => {
    // Regression: after #1 was decided the invoice was shown as "2", the number the flight still had.
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(
      startAfter(0),
      NON_EDITING,
      surface,
      "c1",
    );
    const [first, second, third] = [
      { ...sam, number: 1 },
      { ...flight, number: 2 },
      { ...invoice, number: 3 },
    ];
    await feed(follower, [
      screenFrame([inbound("u1", 1, "11"), workItem("t1", 2, "running")]),
      asking(first),
      asking(first, second),
      asking(second),
      asking(second, third),
    ]);

    expect(sent(calls).map(({ text }) => text)).toEqual([
      SAM_PROMPT,
      '*One more needs your OK:*\n2. Book the 9am flight\n\nReply by number: "yes 2" or "no 2".',
      '*One more needs your OK:*\n3. Pay the invoice\n\nReply by number: "yes 3" or "no 3".',
    ]);
  });

  it("asks each approval once when a second arrives just after the first (run 3 bug 12)", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(
      startAfter(0),
      NON_EDITING,
      surface,
      "c1",
    );
    await feed(follower, [
      screenFrame([inbound("u1", 1, "11"), workItem("t1", 2, "running")]),
      asking(flight),
      asking(flight, invoice),
    ]);

    expect(sent(calls).map(({ text }) => text)).toEqual([
      "*Book the 9am flight*\n\nReply *yes* or *no*.",
      '*One more needs your OK:*\n2. Pay the invoice\n\nReply by number: "yes 2" or "no 2".',
    ]);
  });

  it("asks again after a yes with a change by saying the change (run 4 bug 20)", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(
      startAfter(0),
      NON_EDITING,
      surface,
      "c1",
    );
    const priority = { label: "Priority", value: "high", expandable: false };
    const reAsk = approvalAsked(
      "t1",
      "ap4",
      "Add \u201cPay rent\u201d to your todos",
      null,
      {
        action: "Add a todo",
        question: "Updated priority to high \u2014 still OK to add it?",
        confirm: "add it",
        details: [priority],
        changes: [priority],
        change_note: "Updated priority to high",
      },
    );
    await feed(follower, [
      screenFrame([inbound("u1", 1, "11"), workItem("t1", 2, "running")]),
      asking(reAsk),
    ]);

    expect(sent(calls).map(({ text }) => text)).toEqual([
      "*Updated priority to high \u2014 still OK to add it?*\n\nReply *yes* or *no*.",
    ]);
  });

  it("lists several at once by headline, a changed one with its change", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(
      startAfter(0),
      NON_EDITING,
      surface,
      "c1",
    );
    const rent = approvalAsked(
      "t1",
      "ap5",
      "Add \u201cPay rent\u201d to your todos for tomorrow",
      null,
      { change_note: "Updated priority to high" },
    );
    await feed(follower, [
      screenFrame([inbound("u1", 1, "11"), workItem("t1", 2, "running")]),
      asking(sam, rent),
    ]);

    expect(sent(calls).map(({ text }) => text)).toEqual([
      '*2 things need your OK:*\n1. Email sam@x.com about \u201cQ3 numbers\u201d\n2. Add \u201cPay rent\u201d to your todos for tomorrow (updated priority to high)\n\nReply *yes* to all, *no* to all, or pick some: "yes 1 and 3".',
    ]);
  });

  it("does not ask for an approval from before the follow", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(
      startAfter(5),
      NON_EDITING,
      surface,
      "c1",
    );
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
    const follower = new ConversationFollower(
      startAfter(2),
      NON_EDITING,
      surface,
      "c1",
    );
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
  it("is asked from the follow's opening screen alone", async () => {
    const { surface, calls } = recorder();
    const sam = approvalAsked("t1", "ap1", "Send email to Sam");
    // Woken (after_seq 6) for the approval logged at seq 7, on work started at seq 2.
    const follower = new ConversationFollower(
      startAfter(6),
      NON_EDITING,
      surface,
      "c1",
    );
    await feed(follower, [
      screenFrame([
        inbound("u1", 1, "11"),
        workItem("t1", 2, "awaiting_approval", [sam], 7),
      ]),
      stateFrame(7, "awaiting_approval"),
    ]);

    expect(sent(calls).map(({ text }) => text)).toEqual([
      "*Send email to Sam*\n\nReply *yes* or *no*.",
    ]);
  });
  it("is asked, once", async () => {
    const { surface, calls } = recorder();
    const sam = approvalAsked("t1", "ap1", "Send email to Sam");
    // Woken for the approval logged at seq 7, on work the screen shows at seq 2.
    const follower = new ConversationFollower(
      startAfter(6),
      NON_EDITING,
      surface,
      "c1",
    );
    const asking = workItem("t1", 2, "awaiting_approval", [sam], 7);
    await feed(follower, [
      screenFrame([inbound("u1", 1, "11"), asking]),
      screenFrame([inbound("u1", 1, "11"), asking]),
    ]);

    expect(sent(calls).map(({ text }) => text)).toEqual([
      "*Send email to Sam*\n\nReply *yes* or *no*.",
    ]);
  });
});

describe("numbered approvals across two pieces of work", () => {
  // Mirrors apps/api/tests/unit/services/hil/test_pending.py: the server resolves "2" against the same order.
  it("number by the work's start, not by when each approval was asked", async () => {
    const { surface, calls } = recorder();
    const pay = approvalAsked("task_b", "pay", "Pay the invoice");
    const email = approvalAsked("task_a", "email", "Send email to Sam");
    const follower = new ConversationFollower(
      startAfter(0),
      NON_EDITING,
      surface,
      "c1",
    );
    await feed(follower, [
      screenFrame([
        inbound("u1", 1, "11"),
        workItem("task_a", 2, "running"),
        workItem("task_b", 3, "running"),
      ]),
      updateFrame(workItem("task_b", 3, "awaiting_approval", [pay], 4)),
      updateFrame(workItem("task_a", 2, "awaiting_approval", [email], 5)),
    ]);

    expect(
      sent(calls)
        .map(({ text }) => text)
        .at(-1),
    ).toBe(
      '*One more needs your OK:*\n1. Send email to Sam\n\nReply by number: "yes 1" or "no 1".',
    );
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
      const follower = new ConversationFollower(
        startAfter(3),
        options,
        surface,
        "c1",
      );
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

  it("sends a notice's image as a photo captioned with its first bubble, the rest after it", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(
      startAfter(3),
      EDITING,
      surface,
      "c1",
    );
    const brief = {
      ...noticeItem("n1", 4, "Good morning"),
      bubbles: ["Good morning", "Three things need you"],
      image_url: "https://cdn.test/edition.png",
    };

    await feed(follower, [insertFrame(brief), stateFrame(4, "idle")]);

    expect(calls.filter((call) => call.op !== "send")).toEqual([
      {
        op: "photo",
        url: "https://cdn.test/edition.png",
        caption: "Good morning",
      },
      { op: "notice", bubbles: ["Three things need you"] },
    ]);
  });

  it("sends a notice whose image the platform refused as its text and the image's link", async () => {
    const { surface, calls } = recorder({
      refusePhoto: () => new Error("too large"),
    });
    const follower = new ConversationFollower(
      startAfter(3),
      EDITING,
      surface,
      "c1",
    );
    const brief = {
      ...noticeItem("n1", 4, "Good morning"),
      image_url: "https://cdn.test/edition.png",
    };

    await feed(follower, [insertFrame(brief), stateFrame(4, "idle")]);

    expect(calls.filter((call) => call.op !== "send")).toEqual([
      {
        op: "notice",
        bubbles: ["Good morning", "https://cdn.test/edition.png"],
      },
    ]);
  });

  it("renders a notice's markdown for the platform, like a reply", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(
      startAfter(3),
      SLACK,
      surface,
      "c1",
    );
    await feed(follower, [
      insertFrame(
        noticeItem(
          "n1",
          4,
          "**Call the bank**\nDetails in [the doc](https://doc.test/a)",
        ),
      ),
    ]);

    expect(calls.filter((call) => call.op === "notice")).toEqual([
      {
        op: "notice",
        // Slack's bold, fenced in zero-width spaces so it binds mid-word.
        bubbles: [
          "\u200b*Call the bank*\u200b\nDetails in <https://doc.test/a|the doc>",
        ],
      },
    ]);
  });

  it("names a file the platform refused with where to open it, and goes on", async () => {
    const { surface, calls } = recorder({
      refuseFile: () => new Error("Request failed with status code 413"),
    });
    const follower = new ConversationFollower(
      startAfter(0),
      SLACK,
      surface,
      "c1",
    );
    await feed(follower, [
      screenFrame([inbound("u1", 1, "11")]),
      updateFrame({
        ...replyItem("r1", 2, "Here is the report", "answered"),
        files: [
          {
            path: "out/report.pdf",
            content_type: "application/pdf",
            opens_at: CONVERSATION_LINK,
          },
        ],
      }),
      insertFrame(replyItem("r2", 3, "And one more thing", "answered")),
    ]);

    expect(follower.deliveryFailed).toBe(false);
    expect(calls.filter((call) => call.op === "notice")).toEqual([
      {
        op: "notice",
        bubbles: [
          `I couldn't send report.pdf here. Open it in GAIA: <${CONVERSATION_LINK}|${CONVERSATION_LINK}>`,
        ],
      },
    ]);
    expect(sent(calls).map(({ text }) => text)).toEqual([
      "Here is the report",
      "And one more thing",
    ]);
  });

  it("sends no notice from before the follow", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(
      startAfter(4),
      NON_EDITING,
      surface,
      "c1",
    );
    await feed(follower, [screenFrame([noticeItem("n1", 4, "Old reminder")])]);

    expect(calls.filter((call) => call.op === "notice")).toEqual([]);
  });

  it("uploads the files a settled reply delivers once, after its text", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(
      startAfter(0),
      NON_EDITING,
      surface,
      "c1",
    );
    follower.expect(1);
    const files = [
      {
        path: "out/report.pdf",
        content_type: "application/pdf",
        opens_at: CONVERSATION_LINK,
      },
    ];
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
    const followers = new ConversationFollowers(source, NON_EDITING, NOT_KEPT);
    const ctx = { platform: NON_EDITING.platform, platformUserId: "7" };

    followers.follow(ctx, "c1", 1, cursorAt(0), surface);
    await followers.idle();
    // The wakes for the reply and the notice, consumed after that follow ended.
    followers.resume(ctx, "c1", cursorAt(1), surface);
    await followers.idle();
    followers.resume(ctx, "c1", cursorAt(2), surface);
    await followers.idle();

    expect(screen(calls)).toEqual(["Done."]);
    expect(calls.filter((call) => call.op === "notice")).toHaveLength(1);
  });

  it("delivers a notice owed from before the user's message when the user writes first", async () => {
    const { surface, calls } = recorder();
    // The reminder at seq 2 was logged while the bot was down, and its wake was lost.
    const source: ConversationEventSource = async function* () {
      yield screenFrame([
        inbound("u1", 1, "11"),
        noticeItem("n1", 2, "Your reminder: call the bank"),
        inbound("u2", 3, "12"),
      ]);
      yield* answer(4, "r1", "Done.");
      yield stateFrame(4, "idle");
    };
    const followers = new ConversationFollowers(source, NON_EDITING, NOT_KEPT);
    const ctx = { platform: NON_EDITING.platform, platformUserId: "7" };

    followers.follow(ctx, "c1", 3, cursorAt(1), surface);
    await followers.idle();

    expect(calls.filter((call) => call.op === "notice")).toHaveLength(1);
    expect(screen(calls)).toEqual(["Done."]);
  });
});

describe.each([
  ["editing", EDITING],
  ["non-editing", NON_EDITING],
])("a %s bot that crashes between a reply's bubbles", (_family, options) => {
  it("sends the remaining bubbles once after the restart, and repeats nothing", async () => {
    // The server's copy of the cursor: what the last record left.
    let kept: DeliveryCursor = cursorAt(1);
    const keep = async (cursor: DeliveryCursor) => {
      kept = cursor;
    };
    const reply = replyItem("r1", 2, ["One.", "Two.", "Three."], "answered");
    const before = recorder();
    let sends = 0;
    const crashing: FollowSurface = {
      ...before.surface,
      send: async (text, replyTo) => {
        sends += 1;
        if (sends === 3) throw new Error("bot process died");
        return before.surface.send(text, replyTo);
      },
    };
    const first = new ConversationFollower(
      { floor: 1, partialReply: null, record: keep },
      options,
      crashing,
      "c1",
    );
    await expect(
      feed(first, [
        screenFrame([inbound("u1", 1, "11")]),
        insertFrame(reply),
        stateFrame(2, "idle"),
      ]),
    ).rejects.toThrow("bot process died");

    const resumed = recorder();
    const restarted = new ConversationFollower(
      {
        floor: kept.delivered_seq,
        partialReply: kept.partial_reply,
        record: keep,
      },
      options,
      resumed.surface,
      "c1",
    );
    await feed(restarted, [
      screenFrame([inbound("u1", 1, "11"), reply]),
      stateFrame(2, "idle"),
    ]);

    expect(sent(before.calls).map(({ text }) => text)).toEqual([
      "One.",
      "Two.",
    ]);
    expect(sent(resumed.calls)).toEqual([{ text: "Three.", replyTo: null }]);
    expect(kept).toEqual(cursorAt(2));
  });
});

describe("a live bot that stops while a bubble is still being written (run 4 bug 21)", () => {
  const GUIDE = "1. Preheat the oven to 200C and line a tray.";
  const reply = replyItem("r1", 2, GUIDE, "answered");

  /** The first follow previews the bubble's first words, then the process dies. */
  async function crashMidBubble() {
    let kept: DeliveryCursor = cursorAt(1);
    const keep = async (cursor: DeliveryCursor) => {
      kept = cursor;
    };
    const chat = recorder();
    const first = new ConversationFollower(
      { floor: 1, partialReply: null, record: keep },
      EDITING,
      chat.surface,
      "c1",
    );
    await feed(first, [
      screenFrame([inbound("u1", 1, "11")]),
      insertFrame(replyItem("r1", 2, "1")),
      replyDelta("a-r1", "r1", 0, "1"),
      // The preview the delta scheduled has run by the next frame.
      stateFrame(1, "thinking"),
    ]);
    first.close();
    expect(screen(chat.calls)).toEqual(["1"]);
    const restartWith = (surface: FollowSurface) =>
      new ConversationFollower(
        {
          floor: kept.delivered_seq,
          partialReply: kept.partial_reply,
          record: keep,
        },
        EDITING,
        surface,
        "c1",
      );
    return { chat, kept: () => kept, restartWith };
  }

  const settledWhileDown: ConversationFrame[] = [
    screenFrame([inbound("u1", 1, "11"), reply]),
    stateFrame(2, "idle"),
  ];

  it("finishes the half-written bubble by editing it after the restart, posting nothing new", async () => {
    const { chat, kept, restartWith } = await crashMidBubble();
    const sendsBefore = sent(chat.calls).length;

    await feed(restartWith(chat.surface), settledWhileDown);

    expect(screen(chat.calls)).toEqual([GUIDE]);
    expect(sent(chat.calls)).toHaveLength(sendsBefore);
    expect(kept()).toEqual(cursorAt(2));
  });

  it("deletes the half-written bubble and sends the reply when the platform refuses the edit", async () => {
    const { chat, kept, restartWith } = await crashMidBubble();
    const refusing: FollowSurface = {
      ...chat.surface,
      reopen: (id) => ({
        ...chat.surface.reopen(id),
        edit: async () => {
          throw new Error("Bad Request: message can't be edited");
        },
      }),
    };

    await feed(restartWith(refusing), settledWhileDown);

    expect(screen(chat.calls)).toEqual([GUIDE]);
    expect(kept()).toEqual(cursorAt(2));
  });

  it("never edits the half-written bubble back to less than it showed while the reply still streams", async () => {
    let kept: DeliveryCursor = cursorAt(1);
    const keep = async (cursor: DeliveryCursor) => {
      kept = cursor;
    };
    const chat = recorder();
    const first = new ConversationFollower(
      { floor: 1, partialReply: null, record: keep },
      EDITING,
      chat.surface,
      "c1",
    );
    await feed(first, [
      screenFrame([inbound("u1", 1, "11")]),
      insertFrame(replyItem("r1", 2, "1")),
      replyDelta("a-r1", "r1", 0, "1. Preheat the oven"),
      stateFrame(1, "thinking"),
    ]);
    first.close();
    expect(screen(chat.calls)).toEqual(["1. Preheat the oven"]);

    // The restarted follow opens while the reply is still streaming from its first words.
    const restarted = new ConversationFollower(
      {
        floor: kept.delivered_seq,
        partialReply: kept.partial_reply,
        record: keep,
      },
      EDITING,
      chat.surface,
      "c1",
    );
    await feed(restarted, [
      screenFrame([inbound("u1", 1, "11"), replyItem("r1", 2, "1")]),
      replyDelta("a-r1", "r1", 0, "1. Pre"),
      stateFrame(1, "thinking"),
      replyDelta("a-r1", "r1", 1, "heat the oven to 200C and line a tray."),
      stateFrame(1, "thinking"),
      updateFrame(reply),
      stateFrame(2, "idle"),
    ]);

    expect(takenBack(chat.calls)).toEqual([]);
    expect(screen(chat.calls)).toEqual([GUIDE]);
    expect(kept).toEqual(cursorAt(2));
  });
});

describe("a browser run on a work item", () => {
  const SHOT = "https://cdn.test/step-1.png";
  const LINK = "https://gaia.test/live/abc";
  const REPLAY = "https://gaia.test/replay/r1";
  const browserCard = (data: Record<string, unknown>) => ({
    tool_name: "browser_task_data",
    data,
  });
  const session = browserCard({
    kind: "session",
    task: "book",
    status: "running",
  });
  const step = browserCard({
    kind: "step",
    index: 1,
    goal: "open the booking page.",
    url: "https://example.test/book",
    screenshot: SHOT,
    frame_digest: "f1",
  });
  // The page did not change: the photo already sent shows it.
  const sameFrame = browserCard({ ...step.data, index: 2, goal: "scroll" });
  const handoff = browserCard({
    kind: "handoff",
    handoff_id: "h1",
    reason: "Sign in to finish the booking.",
    status: "pending",
    live_view_url: LINK,
  });
  const result = browserCard({
    kind: "result",
    status: "completed",
    success: true,
    summary: "Booked.",
    replay_url: REPLAY,
  });
  const running = (cards: ReturnType<typeof browserCard>[]) => ({
    ...workItem("t1", 2, "running"),
    timeline: groupedTimeline(cards),
  });
  const frames: ConversationFrame[] = [
    screenFrame([inbound("u1", 1, "11")]),
    insertFrame(running([session])),
    updateFrame(running([session, step, sameFrame, handoff])),
    updateFrame(running([session, step, sameFrame, handoff, result])),
  ];

  it("shows each new step's photo, the hand-off with its link, and the recap, once each", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(
      startAfter(0),
      NON_EDITING,
      surface,
      "c1",
    );

    await feed(follower, [
      ...frames,
      // A reconnect opens on the same screen: nothing is shown twice.
      screenFrame([
        inbound("u1", 1, "11"),
        running([session, step, sameFrame, handoff, result]),
      ]),
    ]);

    expect(calls.filter((call) => call.op !== "typing")).toEqual([
      { op: "photo", url: SHOT, caption: "Step 1 · open the booking page" },
      {
        op: "notice",
        bubbles: [
          "Sign in to finish the booking.",
          `Open the live browser: ${LINK}`,
          "Reply here when you're done, or tell me to stop.",
        ],
      },
      { op: "notice", bubbles: [`📽 Here's a recap of the run: ${REPLAY}`] },
    ]);
  });

  it("shows a step that arrives as a patch to the work item, once", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(
      startAfter(0),
      NON_EDITING,
      surface,
      "c1",
    );
    const steps = ["timeline", "cards", 0, "card", "data"];

    await feed(follower, [
      screenFrame([inbound("u1", 1, "11")]),
      insertFrame(running([session])),
      patchFrame(
        "work:t1",
        [{ op: "set", path: [...steps, 1], value: step.data }],
        2,
      ),
      patchFrame("work:t1", [{ op: "set", path: ["image"], value: null }], 2),
    ]);

    expect(calls.filter((call) => call.op === "photo")).toEqual([
      { op: "photo", url: SHOT, caption: "Step 1 · open the booking page" },
    ]);
    expect(follower.resumeAfter).toBe(2);
  });

  it("reopens on the whole screen after a patch that has no place in the item it holds", async () => {
    const { surface } = recorder();
    const follower = new ConversationFollower(
      startAfter(0),
      NON_EDITING,
      surface,
      "c1",
    );
    await feed(follower, [
      screenFrame([inbound("u1", 1, "11")]),
      insertFrame(running([session])),
    ]);
    const unplaced = patchFrame(
      "work:t1",
      [{ op: "set", path: ["timeline", "cards", 4, "card"], value: {} }],
      2,
    );

    await expect(follower.apply(unplaced)).rejects.toThrow(StaleScreen);
    expect(follower.resumeAfter).toBeNull();
    await feed(follower, [screenFrame([inbound("u1", 1, "11")], 2)]);
    expect(follower.resumeAfter).toBe(2);
  });

  it("shows a run asked for in a group to the requester's own chat, and nothing in the group", async () => {
    const { surface, calls } = recorder({ group: true });
    const follower = new ConversationFollower(
      startAfter(0),
      NON_EDITING,
      surface,
      "c1",
    );

    await feed(follower, frames);

    expect(calls.filter((call) => call.op !== "typing")).toEqual([
      { op: "photo", url: SHOT, caption: "Step 1 · open the booking page" },
      {
        op: "dm",
        bubbles: [
          "Sign in to finish the booking.",
          `Open the live browser: ${LINK}`,
          "Reply here when you're done, or tell me to stop.",
        ],
      },
      { op: "dm", bubbles: [`📽 Here's a recap of the run: ${REPLAY}`] },
    ]);
  });

  it("sends a step photo the platform refused as its caption and link, and goes on", async () => {
    const { surface, calls } = recorder({
      refusePhoto: () => new Error("Bad Request: wrong file identifier"),
    });
    const follower = new ConversationFollower(
      startAfter(0),
      NON_EDITING,
      surface,
      "c1",
    );

    await feed(follower, frames);

    expect(follower.deliveryFailed).toBe(false);
    expect(calls.filter((call) => call.op === "notice")).toEqual([
      { op: "notice", bubbles: [`Step 1 · open the booking page\n${SHOT}`] },
      {
        op: "notice",
        bubbles: [
          "Sign in to finish the booking.",
          `Open the live browser: ${LINK}`,
          "Reply here when you're done, or tell me to stop.",
        ],
      },
      { op: "notice", bubbles: [`📽 Here's a recap of the run: ${REPLAY}`] },
    ]);
  });

  it("ends the follow when the chat itself is gone", async () => {
    const { surface } = recorder({
      refusePhoto: () => new Error("Bad Request: chat not found"),
    });
    const follower = new ConversationFollower(
      startAfter(0),
      NON_EDITING,
      surface,
      "c1",
    );

    await expect(feed(follower, frames)).rejects.toThrow("chat not found");
    expect(follower.deliveryFailed).toBe(true);
  });
});

describe("the follower's typing indicator", () => {
  it("marks typing on the latest user message the reply answers, and stops once GAIA is idle", async () => {
    const { surface, calls } = recorder();
    const follower = new ConversationFollower(startAfter(0), EDITING, surface);

    await feed(follower, [
      screenFrame([inbound("u1", 1, "11"), inbound("u2", 2, "12")]),
      stateFrame(2, "thinking"),
      ...answer(3, "r1", "Both done."),
      stateFrame(3, "idle"),
    ]);

    expect(calls.filter((call) => call.op === "typing")).toEqual([
      { op: "typing", state: "start", on: "12" },
      { op: "typing", state: "stop" },
    ]);
  });
});

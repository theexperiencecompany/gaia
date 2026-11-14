/**
 * Golden conformance suite — the harness's license to exist.
 *
 * For each scenario × platform, this runs the SAME scripted conversation through
 * (a) the harness emulating platform X, and (b) the REAL platform-X adapter with
 * ONLY its SDK boundary faked (grammY / Slack Bolt / discord.js / Kapso). Crucially
 * `@gaia/shared` is NOT mocked — the real post-and-follow path, conversation
 * follower, delivery state machine, markdown converters and length limits all run
 * on both sides. The only faked GAIA seam is the GaiaClient network boundary
 * (`postMessage` / `conversationEvents` / `createLinkToken`).
 *
 * We then reduce each side to a canonical shape — the ordered list of FINAL
 * bubble texts the user ends up seeing, plus every delivered text — and assert
 * they match. If the harness ever re-hardcodes a platform limit, uses the wrong
 * converter, or mis-wires the follower, the two diverge and this suite fails.
 *
 * No live API is required.
 */

import {
  buildAuthLinkMessage,
  buildPlanRequiredMessage,
  type ChatRequest,
  GaiaApiError,
  type PlatformName,
  renderForPlatform,
} from "@gaia/shared/bots";
import { describe, expect, it, vi } from "vitest";
import {
  insertFrame,
  replyDelta,
  replyItem,
  retractFrame,
  screenFrame,
  stateFrame,
  updateFrame,
  userItemWith,
} from "../../../../libs/shared/ts/src/conversation/testing";
import type { ConversationFrame } from "../../../../libs/shared/ts/src/conversation/types";
import { HarnessAdapter } from "../../harness/src/adapter";
import { resolveEmulation } from "../../harness/src/emulation";
import { TranscriptRecorder } from "../../harness/src/transcript";

// ---------------------------------------------------------------------------
// Fake only the platform SDKs. @gaia/shared stays real (aliased to source).
// ---------------------------------------------------------------------------

vi.mock("grammy", () => ({
  Bot: vi.fn(() => ({})),
  GrammyError: class GrammyError extends Error {
    constructor(
      message: string,
      public error_code: number,
      public description: string,
    ) {
      super(message);
      this.name = "GrammyError";
    }
  },
  InputFile: vi.fn(),
}));
vi.mock("@grammyjs/types", () => ({}));
vi.mock("@slack/bolt", () => ({ App: vi.fn(() => ({})) }));
vi.mock("discord.js", () => ({
  ActionRowBuilder: vi.fn(),
  ActivityType: {},
  ButtonBuilder: vi.fn(),
  ButtonStyle: {},
  Client: vi.fn(() => ({})),
  EmbedBuilder: vi.fn(() => ({
    setTitle: vi.fn().mockReturnThis(),
    setDescription: vi.fn().mockReturnThis(),
    setColor: vi.fn().mockReturnThis(),
    setFooter: vi.fn().mockReturnThis(),
    setTimestamp: vi.fn().mockReturnThis(),
    setThumbnail: vi.fn().mockReturnThis(),
    setAuthor: vi.fn().mockReturnThis(),
    addFields: vi.fn().mockReturnThis(),
  })),
  Events: {},
  GatewayIntentBits: {},
  MessageFlags: { Ephemeral: 64 },
  Partials: {},
}));
vi.mock("@kapso/whatsapp-cloud-api", () => ({
  WhatsAppClient: vi.fn(() => ({})),
}));

// Imported AFTER the mocks so each adapter picks up its faked SDK.
import { DiscordAdapter } from "../../discord/src/adapter";
import { SlackAdapter } from "../../slack/src/adapter";
import { TelegramAdapter } from "../../telegram/src/adapter";
import { WhatsAppAdapter } from "../../whatsapp/src/adapter";
import { injectGaia } from "../shared/helpers/inject-gaia";

// ---------------------------------------------------------------------------
// Scripted GAIA client — the only faked GAIA seam.
// ---------------------------------------------------------------------------

interface ApiScript {
  /** The reply's streamed chunks; its saved text is their concatenation. */
  chunks?: string[];
  /** Streamed by an attempt that is retracted before the reply's chunks. */
  preamble?: string;
  /** The post is refused with this error instead of accepted. */
  refuse?: GaiaApiError;
  /** The turn resolves to this emoji ack instead of a text reply. */
  reaction?: string;
}

const AUTH_URL = "https://gaia.example.com/auth?token=conf123";
const PRICING_URL = "https://gaia.example.com/pricing";

/** The frames of one answered turn: the posted message, then the script's reply or reaction. */
function turnFrames(
  script: ApiScript,
  post: ChatRequest | undefined,
): ConversationFrame[] {
  if (!post) throw new Error("the events stream opened before any post");
  const message = (reaction: string | null = null) =>
    userItemWith("u1", 1, {
      text: post.message,
      surface: post.platform,
      platform_message_id: post.platformMessageId ?? null,
      reaction: reaction ? { emoji: reaction, by: "chat_model" } : null,
    });
  const opened = [screenFrame([message()]), stateFrame(1, "thinking")];
  if (script.reaction) {
    return [
      ...opened,
      updateFrame(message(script.reaction)),
      stateFrame(2, "idle"),
    ];
  }
  const chunks = script.chunks ?? [];
  const text = chunks.join("");
  const preamble = script.preamble
    ? [
        insertFrame(replyItem("r1", 2, script.preamble)),
        replyDelta("a0", "r1", 0, script.preamble),
        retractFrame("a0"),
      ]
    : [insertFrame(replyItem("r1", 2, chunks[0] ?? ""))];
  return [
    ...opened,
    ...preamble,
    ...chunks.map((chunk, i) => replyDelta("a1", "r1", i, chunk)),
    updateFrame(replyItem("r1", 2, text, "answered")),
    stateFrame(3, "idle"),
  ];
}

function makeGaia(script: ApiScript) {
  const posts: ChatRequest[] = [];
  return {
    postMessage: vi.fn(async (request: ChatRequest) => {
      if (script.refuse) throw script.refuse;
      posts.push(request);
      return {
        conversation_id: "conv-1",
        message_id: "u1",
        seq: 1,
        session_token: "session",
      };
    }),
    conversationEvents: vi.fn(async function* () {
      yield* turnFrames(script, posts[0]);
    }),
    checkAuthStatus: vi.fn(async () => ({
      authenticated: false,
      platform: "test",
    })),
    createLinkToken: vi.fn(async () => ({ token: "tok", authUrl: AUTH_URL })),
    getPricingUrl: () => PRICING_URL,
  };
}

// Canonical reduction: a keyed set of bubbles (create then update in place,
// gone once deleted), every text delivered by any channel (bubbles +
// ephemerals + DMs), and every emoji attached as a native reaction.

type Op =
  | { op: "create"; id: string; text: string }
  | { op: "update"; id: string; text: string }
  | { op: "delete"; id: string }
  | { op: "react"; emoji: string }
  | { op: "aux"; text: string };

interface Canonical {
  bubbles: string[];
  allTexts: string[];
  reactions: string[];
}

function reduce(ops: Op[]): Canonical {
  const order: string[] = [];
  const byId = new Map<string, string>();
  const allTexts: string[] = [];
  const reactions: string[] = [];
  for (const op of ops) {
    if (op.op === "aux") {
      allTexts.push(op.text);
      continue;
    }
    if (op.op === "react") {
      reactions.push(op.emoji);
      continue;
    }
    if (op.op === "delete") {
      order.splice(order.indexOf(op.id), 1);
      byId.delete(op.id);
      continue;
    }
    if (!byId.has(op.id)) order.push(op.id);
    byId.set(op.id, op.text);
    allTexts.push(op.text);
  }
  return {
    bubbles: order.map((id) => byId.get(id) ?? ""),
    allTexts,
    reactions,
  };
}

/** Reduce a recorded harness transcript into the same canonical shape. */
function reduceTranscript(recorder: TranscriptRecorder): Canonical {
  const ops: Op[] = [];
  for (const event of recorder.getEvents()) {
    if (event.type === "send")
      ops.push({ op: "create", id: event.messageId, text: event.text });
    else if (event.type === "edit")
      ops.push({ op: "update", id: event.messageId, text: event.text });
    else if (event.type === "delete")
      ops.push({ op: "delete", id: event.messageId });
    else if (event.type === "ephemeral")
      ops.push({ op: "aux", text: event.text });
    else if (event.type === "reaction")
      ops.push({ op: "react", emoji: event.emoji });
  }
  return reduce(ops);
}

// ---------------------------------------------------------------------------
// Harness driver
// ---------------------------------------------------------------------------

async function driveHarness(
  platform: PlatformName,
  script: ApiScript,
): Promise<Canonical> {
  const recorder = new TranscriptRecorder(platform);
  const adapter = new HarnessAdapter(resolveEmulation(platform), recorder);
  injectGaia(adapter, makeGaia(script));
  await adapter.simulateMessage("dev-user-1", "please respond");
  await adapter.conversationsIdle();
  return reduceTranscript(recorder);
}

// ---------------------------------------------------------------------------
// Real-adapter drivers — SDK faked, @gaia/shared real.
// ---------------------------------------------------------------------------

async function driveTelegram(script: ApiScript): Promise<Canonical> {
  const adapter = new TelegramAdapter();
  injectGaia(adapter, makeGaia(script));

  const ops: Op[] = [];
  let mid = 100;
  (adapter as unknown as { bot: unknown }).bot = {
    api: {
      sendMessage: vi.fn(async (_chat: number, text: string) => {
        const id = mid++;
        ops.push({ op: "create", id: String(id), text });
        return { message_id: id };
      }),
      editMessageText: vi.fn(
        async (_chat: number, id: number, text: string) => {
          ops.push({ op: "update", id: String(id), text });
          return {};
        },
      ),
      deleteMessage: vi.fn(async (_chat: number, id: number) => {
        ops.push({ op: "delete", id: String(id) });
        return true;
      }),
      sendChatAction: vi.fn(async () => true),
      setMessageReaction: vi.fn(
        async (_chat: string, _id: number, [r]: { emoji: string }[]) => {
          ops.push({ op: "react", emoji: r.emoji });
          return true;
        },
      ),
    },
  };
  const ctx = {
    chat: { id: 555, type: "private" },
    from: { id: 999, first_name: "Dev" },
    msg: { message_id: 7 },
  };

  await (
    adapter as unknown as {
      postTelegramMessage: (
        ctx: unknown,
        userId: string,
        message: string,
      ) => Promise<void>;
    }
  ).postTelegramMessage(ctx, "dev-user-1", "please respond");
  await adapter.conversationsIdle();
  return reduce(ops);
}

async function driveSlack(script: ApiScript): Promise<Canonical> {
  const adapter = new SlackAdapter();
  injectGaia(adapter, makeGaia(script));

  const ops: Op[] = [];
  let ts = 100;
  (adapter as unknown as { app: unknown }).app = {
    client: {
      chat: {
        postMessage: vi.fn(async ({ text }: { text: string }) => {
          const id = `s${ts++}`;
          ops.push({ op: "create", id, text });
          return { ts: id };
        }),
        update: vi.fn(
          async ({ ts: id, text }: { ts: string; text: string }) => {
            ops.push({ op: "update", id, text });
            return {};
          },
        ),
        delete: vi.fn(async ({ ts: id }: { ts: string }) => {
          ops.push({ op: "delete", id });
          return {};
        }),
      },
      reactions: {
        add: vi.fn(async ({ name }: { name: string }) => {
          ops.push({ op: "react", emoji: name });
          return {};
        }),
      },
    },
  };
  // The event's own client carries only the account-link prompt.
  const eventClient = {
    chat: {
      postMessage: vi.fn(async ({ text }: { text: string }) => {
        ops.push({ op: "aux", text });
        return {};
      }),
      postEphemeral: vi.fn(async ({ text }: { text: string }) => {
        ops.push({ op: "aux", text });
        return {};
      }),
    },
  };

  await (
    adapter as unknown as {
      postSlackMessage: (
        client: typeof eventClient,
        channelId: string,
        userId: string,
        message: string,
        isDm: boolean,
        inboundTs: string,
      ) => Promise<void>;
    }
  )
    // A "C..." channel takes the public path: the auth link goes out ephemerally.
    .postSlackMessage(
      eventClient,
      "C999",
      "U999",
      "please respond",
      false,
      "111.1",
    );
  await adapter.conversationsIdle();
  return reduce(ops);
}

async function driveDiscord(script: ApiScript): Promise<Canonical> {
  const adapter = new DiscordAdapter();
  injectGaia(adapter, makeGaia(script));

  const ops: Op[] = [];
  let fid = 100;
  const interaction = {
    options: { getString: vi.fn(() => "please respond") },
    user: {
      id: "dev-user-1",
      send: vi.fn(async (text: string) => {
        ops.push({ op: "aux", text });
      }),
    },
    channelId: "chan-1",
    deferReply: vi.fn(async () => {
      ops.push({ op: "create", id: "reply", text: "" });
    }),
    editReply: vi.fn(async ({ content }: { content: string }) => {
      ops.push({ op: "update", id: "reply", text: content });
    }),
    followUp: vi.fn(async ({ content }: { content: string }) => {
      const id = `f${fid++}`;
      ops.push({ op: "create", id, text: content });
      return {
        edit: vi.fn(async ({ content: c }: { content: string }) => {
          ops.push({ op: "update", id, text: c });
        }),
      };
    }),
  };

  await (
    adapter as unknown as {
      handleGaiaInteraction: (interaction: unknown) => Promise<void>;
    }
  ).handleGaiaInteraction(interaction);
  await adapter.conversationsIdle();
  return reduce(ops);
}

async function driveWhatsApp(script: ApiScript): Promise<Canonical> {
  const adapter = new WhatsAppAdapter();
  injectGaia(adapter, makeGaia(script));
  (adapter as unknown as { waConfig: unknown }).waConfig = {
    kapsoApiKey: "k",
    kapsoPhoneNumberId: "pn",
    kapsoWebhookSecret: "s",
  };

  const ops: Op[] = [];
  let wid = 100;
  (adapter as unknown as { waClient: unknown }).waClient = {
    messages: {
      sendText: vi.fn(async ({ body }: { body: string }) => {
        const id = `w${wid++}`;
        ops.push({ op: "create", id, text: body });
        return { messages: [{ id }] };
      }),
      sendReaction: vi.fn(
        async ({ reaction }: { reaction: { emoji: string } }) => {
          ops.push({ op: "react", emoji: reaction.emoji });
          return {};
        },
      ),
      markRead: vi.fn(async () => ({})),
    },
  };

  await (
    adapter as unknown as {
      postWhatsAppMessage: (
        waId: string,
        text: string,
        messageId: string,
      ) => Promise<void>;
    }
  ).postWhatsAppMessage("dev-user-1", "please respond", "wamid.1");
  await adapter.conversationsIdle();
  return reduce(ops);
}

/**
 * The Discord mention path — the inbound-message analogue of what the harness
 * simulates. The slash-command driver above has no user message to react to.
 */
async function driveDiscordMention(script: ApiScript): Promise<Canonical> {
  const adapter = new DiscordAdapter();
  injectGaia(adapter, makeGaia(script));

  const ops: Op[] = [];
  let mid = 100;
  const react = vi.fn(async (emoji: string) => {
    ops.push({ op: "react", emoji });
  });
  (adapter as unknown as { client: unknown }).client = {
    channels: {
      fetch: vi.fn(async () => ({
        isTextBased: () => true,
        messages: { fetch: vi.fn(async () => ({ react })) },
      })),
    },
  };
  const channelSend = vi.fn(async ({ content }: { content: string }) => {
    const id = `d${mid++}`;
    ops.push({ op: "create", id, text: content });
    return {
      edit: vi.fn(async (updated: string) => {
        ops.push({ op: "update", id, text: updated });
      }),
    };
  });
  const reply = vi.fn(async (text: string) => {
    ops.push({ op: "aux", text });
  });
  const message = {
    id: "msg-in",
    author: { id: "dev-user-1" },
    guild: { id: "guild-1" },
    channelId: "chan-1",
    channel: { send: channelSend, sendTyping: vi.fn(async () => undefined) },
  };

  await (
    adapter as unknown as {
      streamMentionReply: (
        m: typeof message,
        s: typeof reply,
        content: string,
        attachments: unknown[],
      ) => Promise<void>;
    }
  ).streamMentionReply(message, reply, "please respond", []);
  await adapter.conversationsIdle();
  return reduce(ops);
}

const REAL_DRIVERS: Record<PlatformName, (s: ApiScript) => Promise<Canonical>> =
  {
    telegram: driveTelegram,
    slack: driveSlack,
    discord: driveDiscord,
    whatsapp: driveWhatsApp,
    imessage: () => {
      throw new Error("iMessage has no conformance driver");
    },
  };

// ---------------------------------------------------------------------------
// Scenarios
// ---------------------------------------------------------------------------

const PLATFORMS: PlatformName[] = ["discord", "slack", "telegram", "whatsapp"];

/** ~9000 chars of words — comfortably over every platform's length limit. */
const LONG_REPLY = Array.from({ length: 1600 }, (_, i) => `word${i}`).join(" ");

describe("gaia-sim conformance: harness output matches the real adapter", () => {
  describe.each(PLATFORMS)("%s", (platform) => {
    it("plain reply — identical final bubble", async () => {
      const script = { chunks: ["Hello **world**, this is GAIA."] };
      const harness = await driveHarness(platform, script);
      const real = await REAL_DRIVERS[platform](script);
      expect(real.bubbles).toEqual([
        renderForPlatform("Hello **world**, this is GAIA.", platform),
      ]);
      expect(harness.bubbles).toEqual(real.bubbles);
    });

    it("long reply — identical split boundaries", async () => {
      const script = { chunks: [LONG_REPLY] };
      const harness = await driveHarness(platform, script);
      const real = await REAL_DRIVERS[platform](script);

      // More than one bubble means it actually split for this platform's limit.
      expect(real.bubbles.length).toBeGreaterThan(1);
      expect(harness.bubbles).toEqual(real.bubbles);
    }, 20_000);

    it("retracted preamble — both leave only the reply on screen", async () => {
      const script = {
        preamble: "Let me look into your calendar",
        chunks: ["All set, it is on your list."],
      };
      const harness = await driveHarness(platform, script);
      const real = await REAL_DRIVERS[platform](script);

      expect(real.bubbles).toEqual([
        renderForPlatform("All set, it is on your list.", platform),
      ]);
      expect(harness.bubbles).toEqual(real.bubbles);
    }, 10_000);

    it("auth prompt — both deliver the same rendered link message", async () => {
      const script = {
        refuse: new GaiaApiError("API error: 401", 401, {
          code: "NOT_AUTHENTICATED",
        }),
      };
      const harness = await driveHarness(platform, script);
      const real = await REAL_DRIVERS[platform](script);

      const expectedAuth = renderForPlatform(
        buildAuthLinkMessage(AUTH_URL),
        platform,
      );
      expect(harness.allTexts).toContain(expectedAuth);
      expect(real.allTexts).toContain(expectedAuth);
    });

    it("plan gate — both deliver the same rendered upgrade prompt", async () => {
      const script = { refuse: new GaiaApiError("API error: 402", 402) };
      const harness = await driveHarness(platform, script);
      const real = await REAL_DRIVERS[platform](script);

      const expectedUpgrade = renderForPlatform(
        buildPlanRequiredMessage(PRICING_URL),
        platform,
      );
      expect(harness.allTexts).toContain(expectedUpgrade);
      expect(real.allTexts).toContain(expectedUpgrade);
    });

    it("reaction turn — both attach the emoji and leave no bubble", async () => {
      const script = { reaction: "👍" };
      const harness = await driveHarness(platform, script);
      const drive =
        platform === "discord" ? driveDiscordMention : REAL_DRIVERS[platform];
      const real = await drive(script);

      // Slack attaches by shortcode, so compare the count; the text half is exact.
      expect(harness.reactions).toHaveLength(1);
      expect(real.reactions).toHaveLength(1);
      expect(harness.bubbles).toEqual([]);
      expect(real.bubbles).toEqual([]);
    });
  });
});

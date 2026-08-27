/**
 * Golden conformance suite — the harness's license to exist.
 *
 * For each scenario × platform, this runs the SAME scripted chat stream through
 * (a) the harness emulating platform X, and (b) the REAL platform-X adapter with
 * ONLY its SDK boundary faked (grammY / Slack Bolt / discord.js / Kapso). Crucially
 * `@gaia/shared` is NOT mocked — the real streaming pipeline, markdown converters,
 * length limits, and splitting all run on both sides. The only faked GAIA seam is
 * the GaiaClient network boundary (`chatStream` / `createLinkToken`).
 *
 * We then reduce each side to a canonical shape — the ordered list of FINAL
 * bubble texts the user ends up seeing, plus every delivered text — and assert
 * they match. If the harness ever re-hardcodes a platform limit, uses the wrong
 * converter, or mis-wires streaming, the two diverge and this suite fails.
 *
 * No live API is required.
 */

import {
  buildAuthLinkMessage,
  buildPlanRequiredMessage,
  type PlatformName,
  renderForPlatform,
} from "@gaia/shared/bots";
import { describe, expect, it, vi } from "vitest";
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

// ---------------------------------------------------------------------------
// Scripted GAIA client — the only faked GAIA seam.
// ---------------------------------------------------------------------------

interface StreamScript {
  chunks?: string[];
  error?: string;
  authUrl?: string;
}

const AUTH_URL = "https://gaia.example.com/auth?token=conf123";
const PRICING_URL = "https://gaia.example.com/pricing";

function makeGaia(script: StreamScript) {
  return {
    chatStream: vi.fn(
      async (
        _req: unknown,
        onChunk: (t: string) => void | Promise<void>,
        onDone: (full: string, conv: string) => void | Promise<void>,
        onError: (e: Error) => void | Promise<void>,
      ) => {
        if (script.error) {
          await onError(new Error(script.error));
          return "";
        }
        const chunks = script.chunks ?? [];
        for (const chunk of chunks) await onChunk(chunk);
        await onDone(chunks.join(""), "conv-1");
        return "conv-1";
      },
    ),
    createLinkToken: vi.fn(async () => ({
      token: "tok",
      authUrl: script.authUrl ?? AUTH_URL,
    })),
    getPricingUrl: () => PRICING_URL,
  };
}

// ---------------------------------------------------------------------------
// Canonical reduction: a keyed set of bubbles (create then update in place),
// plus every text delivered by any channel (bubbles + ephemerals + DMs).
// ---------------------------------------------------------------------------

type Op =
  | { op: "create"; id: string; text: string }
  | { op: "update"; id: string; text: string }
  | { op: "aux"; text: string };

interface Canonical {
  bubbles: string[];
  allTexts: string[];
}

function reduce(ops: Op[]): Canonical {
  const order: string[] = [];
  const byId = new Map<string, string>();
  const allTexts: string[] = [];
  for (const op of ops) {
    if (op.op === "aux") {
      allTexts.push(op.text);
      continue;
    }
    if (!byId.has(op.id)) order.push(op.id);
    byId.set(op.id, op.text);
    allTexts.push(op.text);
  }
  return { bubbles: order.map((id) => byId.get(id) ?? ""), allTexts };
}

/** Reduce a recorded harness transcript into the same canonical shape. */
function reduceTranscript(recorder: TranscriptRecorder): Canonical {
  const ops: Op[] = [];
  for (const event of recorder.getEvents()) {
    if (event.type === "send")
      ops.push({ op: "create", id: event.messageId, text: event.text });
    else if (event.type === "edit")
      ops.push({ op: "update", id: event.messageId, text: event.text });
    else if (event.type === "ephemeral")
      ops.push({ op: "aux", text: event.text });
  }
  return reduce(ops);
}

// ---------------------------------------------------------------------------
// Harness driver
// ---------------------------------------------------------------------------

async function driveHarness(
  platform: PlatformName,
  script: StreamScript,
): Promise<Canonical> {
  const recorder = new TranscriptRecorder(platform);
  const adapter = new HarnessAdapter(resolveEmulation(platform), recorder);
  (adapter as unknown as { gaia: unknown }).gaia = makeGaia(script);
  await adapter.simulateMessage("dev-user-1", "please respond");
  return reduceTranscript(recorder);
}

// ---------------------------------------------------------------------------
// Real-adapter drivers — SDK faked, @gaia/shared real.
// ---------------------------------------------------------------------------

async function driveTelegram(script: StreamScript): Promise<Canonical> {
  const adapter = new TelegramAdapter();
  (adapter as unknown as { gaia: unknown }).gaia = makeGaia(script);
  (adapter as unknown as { botUsername: string }).botUsername = "gaiabot";

  const ops: Op[] = [];
  let mid = 100;
  const ctx = {
    chat: { id: 555, type: "private" },
    from: { id: 999, first_name: "Dev" },
    reply: vi.fn(async (text: string) => {
      const id = `t${mid++}`;
      ops.push({ op: "create", id, text });
      return { message_id: id };
    }),
    api: {
      editMessageText: vi.fn(async (_c: number, id: string, text: string) => {
        ops.push({ op: "update", id, text });
        return {};
      }),
      sendMessage: vi.fn(async (target: string, text: string) => {
        // Auth DM to the user in a group; here (private) unused, recorded as aux.
        ops.push({ op: "aux", text });
        return { message_id: `x${mid++}` };
      }),
      sendChatAction: vi.fn(async () => ({})),
    },
  };

  await (
    adapter as unknown as {
      handleTelegramStreaming: (
        ctx: typeof ctx,
        userId: string,
        message: string,
      ) => Promise<void>;
    }
  ).handleTelegramStreaming(ctx, "dev-user-1", "please respond");
  return reduce(ops);
}

async function driveSlack(script: StreamScript): Promise<Canonical> {
  const adapter = new SlackAdapter();
  (adapter as unknown as { gaia: unknown }).gaia = makeGaia(script);

  const ops: Op[] = [];
  let ts = 100;
  const client = {
    chat: {
      postMessage: vi.fn(
        async ({ text }: { channel: string; text: string }) => {
          const id = `s${ts++}`;
          ops.push({ op: "create", id, text });
          return { ts: id };
        },
      ),
      update: vi.fn(async ({ ts: id, text }: { ts: string; text: string }) => {
        ops.push({ op: "update", id, text });
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
      handleSlackStreaming: (
        client: typeof client,
        channelId: string,
        userId: string,
        message: string,
      ) => Promise<void>;
    }
  )
    // Channel id "U..." (not "D...") → public path, so an auth link is delivered
    // ephemerally, exactly like production.
    .handleSlackStreaming(client, "U999", "U999", "please respond");
  return reduce(ops);
}

async function driveDiscord(script: StreamScript): Promise<Canonical> {
  const adapter = new DiscordAdapter();
  (adapter as unknown as { gaia: unknown }).gaia = makeGaia(script);

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
      handleGaiaInteraction: (interaction: typeof interaction) => Promise<void>;
    }
  ).handleGaiaInteraction(interaction);
  return reduce(ops);
}

async function driveWhatsApp(script: StreamScript): Promise<Canonical> {
  const adapter = new WhatsAppAdapter();
  (adapter as unknown as { gaia: unknown }).gaia = makeGaia(script);
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
    },
  };

  await (
    adapter as unknown as {
      handleStreamingMessage: (waId: string, text: string) => Promise<void>;
    }
  ).handleStreamingMessage("dev-user-1", "please respond");
  return reduce(ops);
}

const REAL_DRIVERS: Record<
  PlatformName,
  (s: StreamScript) => Promise<Canonical>
> = {
  telegram: driveTelegram,
  slack: driveSlack,
  discord: driveDiscord,
  whatsapp: driveWhatsApp,
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
      expect(harness.bubbles).toEqual(real.bubbles);
    });

    it("long reply — identical split boundaries", async () => {
      const script = { chunks: [LONG_REPLY] };
      const harness = await driveHarness(platform, script);
      const real = await REAL_DRIVERS[platform](script);

      // More than one bubble means it actually split for this platform's limit.
      expect(real.bubbles.length).toBeGreaterThan(1);
      expect(harness.bubbles).toEqual(real.bubbles);
    });

    it("auth prompt — both deliver the same rendered link message", async () => {
      const script = { error: "not_authenticated" };
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
      const script = { error: "plan_required" };
      const harness = await driveHarness(platform, script);
      const real = await REAL_DRIVERS[platform](script);

      const expectedUpgrade = renderForPlatform(
        buildPlanRequiredMessage(PRICING_URL),
        platform,
      );
      expect(harness.allTexts).toContain(expectedUpgrade);
      expect(real.allTexts).toContain(expectedUpgrade);
    });
  });
});

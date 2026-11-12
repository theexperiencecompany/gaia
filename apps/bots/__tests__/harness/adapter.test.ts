/**
 * Unit tests for the HarnessAdapter in isolation.
 *
 * These use the REAL @gaia/shared (aliased to source by vitest.config.ts): the
 * real post-and-follow path, conversation follower, delivery state machine,
 * markdown converters and limits. Only the GaiaClient's network boundary is
 * faked (`postMessage` answers, `conversationEvents` replays scripted frames),
 * and the tests assert the transcript the harness records.
 *
 * Covered:
 * 1. plain reply → one send bubble, rendered by the emulated platform's converter
 * 2. markdown fidelity → WhatsApp `**bold**` becomes `*bold*` (real converter)
 * 3. long reply → split into multiple bubbles, each within the platform limit
 * 4. auth prompt → the rendered "link your account" message is delivered
 * 5. plan gate → the rendered upgrade prompt with the pricing URL is delivered
 * 6. edit support → Telegram edits in place; WhatsApp only ever sends
 * 7. quoting → a reply that quotes the message records its replyTo
 * 8. outbound delivery → deliverOutbound records an outbound-delivery event
 * 8b. outbound photo → deliverOutboundFile fetches the bytes and records the caption
 * 9. command path → an ephemeral reply records an ephemeral event
 * 10. bursts → every message is posted the moment it arrives
 * 11. reactions → a live emoji ack and an outbound reaction record reaction events
 */

import {
  type ChatRequest,
  GaiaApiError,
  type PlatformName,
} from "@gaia/shared/bots";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  entryFrame,
  entryUpdatedFrame,
  replyDelta,
  reply as replyEntry,
  replySettled,
  stateFrame,
  userMessage,
} from "../../../../libs/shared/ts/src/conversation/testing";
import type { ConversationFrame } from "../../../../libs/shared/ts/src/conversation/types";
import { HarnessAdapter } from "../../harness/src/adapter";
import { resolveEmulation } from "../../harness/src/emulation";
import { TranscriptRecorder } from "../../harness/src/transcript";
import type {
  InboundEvent,
  TranscriptEvent,
} from "../../harness/src/transcript.types";
import { injectGaia } from "../shared/helpers/inject-gaia";

/** What the fake API does with a posted message. */
interface ApiScript {
  /** The reply's streamed chunks; its saved text is their concatenation. */
  chunks?: string[];
  /** The post is refused with this error instead of accepted. */
  refuse?: GaiaApiError;
  authUrl?: string;
  /** The turn resolves to this emoji ack on the newest message instead of a reply. */
  reaction?: string;
  /** The reply natively quotes the newest message. */
  quote?: boolean;
}

const NOT_LINKED = new GaiaApiError("API error: 401", 401, {
  code: "NOT_AUTHENTICATED",
});
const PLAN_REQUIRED = new GaiaApiError("API error: 402", 402);

/** The frames a conversation's events stream carries for these posts and the script's answer. */
function turnFrames(
  script: ApiScript,
  posts: readonly ChatRequest[],
): ConversationFrame[] {
  const count = posts.length;
  const ids = posts.map((_, i) => `u${i + 1}`);
  const message = (i: number) => ({
    ...userMessage(ids[i], posts[i].message),
    surface: posts[i].platform,
    platform_message_id: posts[i].platformMessageId ?? null,
  });
  const frames: ConversationFrame[] = [
    ...posts.map((_, i) => entryFrame(i + 1, message(i))),
    stateFrame(count, "thinking"),
  ];
  if (script.reaction) {
    const last = count - 1;
    return [
      ...frames,
      entryUpdatedFrame(count, {
        ...message(last),
        reaction: { emoji: script.reaction, by: "chat_model" },
        revision: 1,
      }),
      entryFrame(count + 1, replySettled("r1", ids, count, null, "silent")),
      stateFrame(count + 1, "idle"),
    ];
  }
  const chunks = script.chunks ?? [];
  const text = chunks.join("");
  const quote = script.quote ? ids[count - 1] : null;
  return [
    ...frames,
    entryFrame(count + 1, replyEntry("r1", "a1")),
    ...chunks.map((chunk, i) => replyDelta("a1", "r1", i, chunk)),
    entryUpdatedFrame(count + 1, replyEntry("r1", "a1", text, 1)),
    entryFrame(count + 2, replySettled("r1", ids, count + 1, quote)),
    stateFrame(count + 2, "idle"),
  ];
}

/**
 * A scripted stand-in for the GaiaClient network boundary. The events stream
 * waits for `held` before replaying, so a test can post a burst first.
 */
function makeGaia(script: ApiScript, held: Promise<void> = Promise.resolve()) {
  const posts: ChatRequest[] = [];
  return {
    posts,
    postMessage: vi.fn(async (request: ChatRequest) => {
      if (script.refuse) throw script.refuse;
      posts.push(request);
      return {
        conversation_id: "c1",
        message_id: `u${posts.length}`,
        seq: posts.length,
        session_token: "session",
      };
    }),
    conversationEvents: vi.fn(async function* () {
      await held;
      for (const frame of turnFrames(script, posts)) {
        yield { stream_id: null, frame };
      }
    }),
    createLinkToken: vi.fn(async () => ({
      token: "tok",
      authUrl: script.authUrl ?? "https://gaia.test/auth?token=abc123",
    })),
    getPricingUrl: () => "https://gaia.test/pricing",
  };
}

type FakeGaia = ReturnType<typeof makeGaia>;

/** Builds a harness adapter for `platform` with a scripted gaia injected. */
function makeAdapter(
  platform: PlatformName,
  script: ApiScript,
  held?: Promise<void>,
): { adapter: HarnessAdapter; recorder: TranscriptRecorder; gaia: FakeGaia } {
  const recorder = new TranscriptRecorder(platform);
  const adapter = new HarnessAdapter(resolveEmulation(platform), recorder);
  const gaia = makeGaia(script, held);
  injectGaia(adapter, gaia);
  return { adapter, recorder, gaia };
}

/** Convenience: drive one message, wait for its replies, and return the recorded events. */
async function drive(
  platform: PlatformName,
  script: ApiScript,
  message: string,
): Promise<readonly TranscriptEvent[]> {
  const { adapter, recorder } = makeAdapter(platform, script);
  await adapter.simulateMessage("dev-user-1", message);
  await adapter.conversationsIdle();
  return recorder.getEvents();
}

const sends = (events: readonly TranscriptEvent[]) =>
  events.filter((e) => e.type === "send");
const texts = (events: readonly TranscriptEvent[]) =>
  events.flatMap((e) => ("text" in e ? [e.text] : []));

describe("HarnessAdapter — plain reply", () => {
  it("records inbound, typing, and a single send bubble", async () => {
    const events = await drive(
      "telegram",
      { chunks: ["Hello world"] },
      "hi there",
    );
    const types = events.map((e) => e.type);
    expect(types).toContain("inbound");
    expect(types).toContain("typing");
    expect(sends(events)).toHaveLength(1);
    expect(sends(events)[0]).toMatchObject({ text: "Hello world" });
  });

  it("posts the message with the inbound message's id", async () => {
    const { adapter, recorder, gaia } = makeAdapter("telegram", {
      chunks: ["ok"],
    });

    await adapter.simulateMessage("dev-user-1", "hi there");
    await adapter.conversationsIdle();

    const inbound = recorder
      .getEvents()
      .find((e): e is InboundEvent => e.type === "inbound");
    expect(gaia.posts).toEqual([
      {
        message: "hi there",
        platform: "telegram",
        platformUserId: "dev-user-1",
        channelId: "dev-user-1",
        platformMessageId: inbound?.messageId,
      },
    ]);
  });
});

describe("HarnessAdapter — markdown fidelity via the real converter", () => {
  it("renders WhatsApp bold with the platform's real converter", async () => {
    const events = await drive("whatsapp", { chunks: ["**Bold** move"] }, "hi");
    // convertToWhatsAppMarkdown turns **bold** into *bold* — proving the harness
    // uses the emulated platform's real converter, not a re-hardcoded one.
    expect(sends(events)[0]).toMatchObject({ text: "*Bold* move" });
  });

  it("renders Telegram HTML with the platform's real converter", async () => {
    const events = await drive("telegram", { chunks: ["**Bold** move"] }, "hi");
    expect(sends(events)[0]).toMatchObject({ text: "<b>Bold</b> move" });
  });
});

describe("HarnessAdapter — long reply splitting", () => {
  it("splits a reply over the Telegram limit into multiple in-limit bubbles", async () => {
    // ~9000 chars of words → split at the 4096 limit.
    const long = Array.from({ length: 1500 }, (_, i) => `word${i}`).join(" ");
    const events = await drive("telegram", { chunks: [long] }, "tell me lots");

    const sendEvents = sends(events);
    expect(sendEvents.length).toBeGreaterThan(1);
    for (const send of sendEvents) {
      expect(send.length).toBeLessThanOrEqual(4096);
    }
  }, 10_000);
});

describe("HarnessAdapter — auth prompt", () => {
  it("delivers the rendered auth-link message when the account is not linked", async () => {
    const events = await drive(
      "telegram",
      { refuse: NOT_LINKED, authUrl: "https://gaia.test/auth?t=xyz" },
      "do something",
    );
    const delivered = texts(events).join("\n");
    expect(delivered).toContain("https://gaia.test/auth?t=xyz");
    expect(delivered).toContain("Link your account");
  });
});

describe("HarnessAdapter — plan gate", () => {
  it("delivers the rendered upgrade prompt when the plan refuses the post", async () => {
    const events = await drive(
      "telegram",
      { refuse: PLAN_REQUIRED },
      "do something",
    );
    const delivered = texts(events).join("\n");
    expect(delivered).toContain("https://gaia.test/pricing");
    expect(delivered).toContain("Pro");
  });
});

describe("HarnessAdapter — edit semantics", () => {
  it("Telegram edits a bubble in place (supportsEdit = true)", async () => {
    // The first chunk previews into a new bubble; the settled reply edits it.
    const events = await drive(
      "telegram",
      { chunks: ["Hello ", "world"] },
      "hi",
    );
    expect(events.some((e) => e.type === "edit")).toBe(true);
    expect(sends(events)).toHaveLength(1);
  });

  it("WhatsApp never edits — every update is a new send (supportsEdit = false)", async () => {
    const events = await drive(
      "whatsapp",
      { chunks: ["Hello ", "world"] },
      "hi",
    );
    expect(events.some((e) => e.type === "edit")).toBe(false);
    expect(sends(events)).toEqual([
      expect.objectContaining({ text: "Hello world" }),
    ]);
  });
});

describe("HarnessAdapter — quoting", () => {
  it("records the inbound message a quoting reply answers natively", async () => {
    const events = await drive(
      "whatsapp",
      { chunks: ["Booked."], quote: true },
      "book it",
    );
    const inbound = events.find((e): e is InboundEvent => e.type === "inbound");
    expect(sends(events)).toEqual([
      expect.objectContaining({ text: "Booked.", replyTo: inbound?.messageId }),
    ]);
  });

  it("records no replyTo on a reply that quotes nothing", async () => {
    const events = await drive("whatsapp", { chunks: ["Done."] }, "hi");
    expect(sends(events)[0]).not.toHaveProperty("replyTo");
  });
});

describe("HarnessAdapter — outbound delivery", () => {
  it("records an outbound-delivery event from deliverOutbound", async () => {
    const recorder = new TranscriptRecorder("telegram");
    const adapter = new HarnessAdapter(resolveEmulation("telegram"), recorder);
    await (
      adapter as unknown as {
        deliverOutbound: (id: string, text: string) => Promise<void>;
      }
    ).deliverOutbound("dev-telegram-42", "Your reminder is due");

    expect(recorder.getEvents()).toEqual([
      expect.objectContaining({
        type: "outbound-delivery",
        destinationId: "dev-telegram-42",
        text: "Your reminder is due",
      }),
    ]);
  });

  it("records the caption and fetched size of an outbound photo", async () => {
    // A browser step photo's caption ("Step 3 · …") is the only thing the user
    // reads under the screenshot, so the transcript has to carry it — otherwise
    // a run that delivers every step looks identical to one that delivers none.
    const recorder = new TranscriptRecorder("telegram");
    const adapter = new HarnessAdapter(resolveEmulation("telegram"), recorder);
    (
      adapter as unknown as {
        gaia: { downloadAttachmentUrl: () => Promise<unknown> };
      }
    ).gaia = {
      downloadAttachmentUrl: async () => ({
        data: Buffer.from("png-bytes"),
        contentType: "image/png",
      }),
    };

    await (
      adapter as unknown as {
        deliverOutboundFile: (
          id: string,
          attachment: Record<string, unknown>,
        ) => Promise<void>;
      }
    ).deliverOutboundFile("dev-telegram-42", {
      url: "http://localhost:8121/shots/c0de/3.png",
      filename: "browser-step-3.png",
      caption: "Step 3 · read the top story",
    });

    expect(recorder.getEvents()).toEqual([
      expect.objectContaining({
        type: "outbound-attachment",
        destinationId: "dev-telegram-42",
        filename: "browser-step-3.png",
        text: "Step 3 · read the top story",
        bytes: 9,
        contentType: "image/png",
      }),
    ]);
  });
});

describe("HarnessAdapter — command path", () => {
  let recorder: TranscriptRecorder;
  let adapter: HarnessAdapter;

  beforeEach(() => {
    ({ adapter, recorder } = makeAdapter("telegram", {}));
  });

  it("routes an unknown /command through dispatch and records an ephemeral", async () => {
    // The base dispatchCommand sends "Unknown command" via sendEphemeral when no
    // command is registered — proving the command path reaches the harness target.
    await adapter.simulateMessage("dev-user-1", "/nope");
    const ephemeral = recorder.getEvents().find((e) => e.type === "ephemeral");
    expect(ephemeral).toBeDefined();
    expect(ephemeral).toMatchObject({ text: expect.stringContaining("nope") });
  });
});

describe("TranscriptRecorder — wall-clock stamp", () => {
  it("stamps each event with the wall-clock time, so two senders' transcripts interleave", () => {
    // A "stop" sent mid-run is answered in its own sender's transcript; the
    // battery orders it against the run's deliveries by this stamp.
    const before = Date.now();
    const recorder = new TranscriptRecorder("telegram");

    const event = recorder.record({ type: "typing", state: "start" });

    expect(event.at).toBeGreaterThanOrEqual(before);
    expect(event.at).toBeLessThanOrEqual(Date.now());
  });
});

describe("HarnessAdapter — a burst of inbound messages", () => {
  /** An adapter whose conversation replays nothing until the test releases it. */
  function heldAdapter(platform: PlatformName) {
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    return { ...makeAdapter(platform, { chunks: ["reply"] }, held), release };
  }

  it.each<PlatformName>(["telegram", "whatsapp", "slack", "discord"])(
    "%s posts every message the moment it arrives, and one reply answers them all",
    async (platform) => {
      const { adapter, recorder, gaia, release } = heldAdapter(platform);

      await adapter.simulateMessage("dev-user-1", "one");
      await adapter.simulateMessage("dev-user-1", "two");

      expect(gaia.posts.map((p) => p.message)).toEqual(["one", "two"]);
      expect(sends(recorder.getEvents())).toEqual([]);

      release();
      await adapter.conversationsIdle();
      expect(texts(sends(recorder.getEvents()))).toEqual(["reply"]);
    },
  );

  it("still posts the next message after one fails, and reports the failure", async () => {
    const { adapter, gaia, release } = heldAdapter("telegram");
    const boom = new Error("handler crashed");
    (adapter as unknown as { dispatchCommand: unknown }).dispatchCommand = vi
      .fn()
      .mockRejectedValue(boom);

    await expect(adapter.simulateMessage("dev-user-1", "/todo")).rejects.toBe(
      boom,
    );
    await adapter.simulateMessage("dev-user-1", "two");

    expect(gaia.posts.map((p) => p.message)).toEqual(["two"]);
    release();
    await adapter.conversationsIdle();
  });
});

describe("HarnessAdapter — reactions", () => {
  it.each<PlatformName>(["telegram", "slack", "discord", "whatsapp"])(
    "%s records the live ack as a reaction on the inbound message, and no text",
    async (platform) => {
      const events = await drive(
        platform,
        { reaction: "😅" },
        "that fixed it, thanks",
      );

      const inbound = events.find(
        (e): e is InboundEvent => e.type === "inbound",
      );
      expect(inbound?.messageId).toBeTruthy();
      expect(events.filter((e) => e.type === "reaction")).toEqual([
        expect.objectContaining({
          destinationId: "dev-user-1",
          targetMessageId: inbound?.messageId,
          emoji: "😅",
          replaces: null,
        }),
      ]);
      expect(events.some((e) => e.type === "send" || e.type === "edit")).toBe(
        false,
      );
    },
  );

  it("records an outbound reaction natively rather than as text", async () => {
    const recorder = new TranscriptRecorder("telegram");
    const adapter = new HarnessAdapter(resolveEmulation("telegram"), recorder);

    await (
      adapter as unknown as {
        deliverOutboundReaction: (
          id: string,
          reaction: { target_platform_message_id: string; emoji: string },
          isChannel: boolean,
        ) => Promise<void>;
      }
    ).deliverOutboundReaction(
      "dev-telegram-42",
      { target_platform_message_id: "in7", emoji: "👍" },
      false,
    );

    expect(recorder.getEvents()).toEqual([
      expect.objectContaining({
        type: "reaction",
        destinationId: "dev-telegram-42",
        targetMessageId: "in7",
        emoji: "👍",
      }),
    ]);
  });
});

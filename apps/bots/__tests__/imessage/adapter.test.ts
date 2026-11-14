import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("spectrum-ts", () => ({
  Spectrum: vi.fn(),
  attachment: vi.fn((input: unknown, options: unknown) => ({
    __attachment: { input, options },
    build: vi.fn(),
  })),
  reaction: vi.fn((emoji: string, target: unknown) => ({
    __reaction: { emoji, target },
    build: vi.fn(),
  })),
  reply: vi.fn((text: string, target: unknown) => ({
    __reply: { text, target },
    build: vi.fn(),
  })),
}));

vi.mock("spectrum-ts/providers/imessage", () => {
  const imessage = Object.assign(
    vi.fn((value: unknown) => value),
    { config: vi.fn(() => ({})), is: vi.fn(() => true) },
  );
  return { imessage };
});

vi.mock("hono", () => ({
  Hono: vi.fn().mockImplementation(() => ({
    get: vi.fn(),
    post: vi.fn(),
    fetch: vi.fn(),
  })),
}));

vi.mock("@hono/node-server", () => ({
  serve: vi.fn(),
}));

vi.mock("@gaia/shared/bots", async () => {
  const { makeGaiaSharedMock } = await import("../shared/mocks/gaiaSharedBase");
  const real = await import("../../../../libs/shared/ts/src/bots/utils");
  return makeGaiaSharedMock("imessage", {
    streamingDefaults: {
      imessage: {
        editIntervalMs: 2000,
        streaming: false,
        platform: "imessage",
      },
    },
    converters: {
      extractSubcommandArgs: vi.fn(real.extractSubcommandArgs),
      friendlyMediaError: vi.fn(real.friendlyMediaError),
      MediaReadTimeoutError: real.MediaReadTimeoutError,
      unfetchableMediaMessage: vi.fn(real.unfetchableMediaMessage),
      unsupportedMediaMessage: vi.fn(real.unsupportedMediaMessage),
      mediaKindFromMime: vi.fn(real.mediaKindFromMime),
      readBodyBytesBounded: vi.fn(real.readBodyBytesBounded),
      readStreamBytesCapped: vi.fn(real.readStreamBytesCapped),
      BODY_TOO_LARGE: real.BODY_TOO_LARGE,
      BODY_READ_TIMEOUT: real.BODY_READ_TIMEOUT,
      WEBHOOK_MAX_BODY_BYTES: real.WEBHOOK_MAX_BODY_BYTES,
    },
  });
});

import { MEDIA_READ_TIMEOUT_MS } from "@gaia/shared/bots";
import { attachment, reaction, reply } from "spectrum-ts";
import { ImessageAdapter } from "../../imessage/src/adapter";
import {
  lastAuthHandler,
  lastSurface,
  postAndFollowSpy,
} from "../shared/mocks/postAndFollow";

interface FakeSpace {
  id: string;
  type: "dm" | "group";
  send: ReturnType<typeof vi.fn>;
  getMessage: ReturnType<typeof vi.fn>;
  startTyping: ReturnType<typeof vi.fn>;
  stopTyping: ReturnType<typeof vi.fn>;
}

function makeSpace(overrides: Partial<FakeSpace> = {}): FakeSpace {
  return {
    id: "any;-;+15550100",
    type: "dm",
    send: vi.fn(async () => ({ id: "sent-1" })),
    getMessage: vi.fn(async (id: string) => ({ id })),
    startTyping: vi.fn(async () => undefined),
    stopTyping: vi.fn(async () => undefined),
    ...overrides,
  };
}

const ATTACHMENT_CHUNK = 256;
const CAP = 1000;

function makeAttachment(overrides: { size?: number } = {}) {
  const content = {
    type: "attachment" as const,
    id: "att-1",
    name: "photo.jpg",
    mimeType: "image/jpeg",
    size: overrides.size ?? 1024,
    produced: 0,
    cancelled: false,
    read: vi.fn(async () => Buffer.alloc(ATTACHMENT_CHUNK)),
    stream: vi.fn(
      async () =>
        new ReadableStream<Uint8Array>({
          pull(controller) {
            content.produced += ATTACHMENT_CHUNK;
            controller.enqueue(new Uint8Array(ATTACHMENT_CHUNK));
          },
          cancel() {
            content.cancelled = true;
          },
        }),
    ),
  };
  return content;
}

function makeVoice(overrides: { id?: string } = { id: "voice-1" }) {
  const content = {
    type: "voice" as const,
    id: overrides.id,
    mimeType: "audio/ogg",
    duration: 4,
    size: 2048,
    produced: 0,
    cancelled: false,
    read: vi.fn(async () => Buffer.alloc(ATTACHMENT_CHUNK)),
    stream: vi.fn(
      async () =>
        new ReadableStream<Uint8Array>({
          pull(controller) {
            content.produced += ATTACHMENT_CHUNK;
            controller.enqueue(new Uint8Array(ATTACHMENT_CHUNK));
          },
          cancel() {
            content.cancelled = true;
          },
        }),
    ),
  };
  return content;
}

function makeMessage(overrides: Record<string, unknown> = {}) {
  return {
    id: `msg-${Math.random().toString(36).slice(2)}`,
    direction: "inbound",
    sender: { id: "+15550100" },
    content: { type: "text", text: "hello" },
    ...overrides,
  };
}

type PrivateAdapter = {
  sendImessageText: (
    space: FakeSpace,
    text: string,
  ) => Promise<{ id: string; edit: (t: string) => Promise<void> }>;
  createImessageTarget: (
    handle: string,
    space: FakeSpace,
  ) => {
    platform: string;
    userId: string;
    channelId: string;
    send: (t: string) => Promise<{ id: string }>;
    sendEphemeral: (t: string) => Promise<{ id: string }>;
    startTyping: () => Promise<() => void>;
  };
  handleInboundMessage: (space: FakeSpace, message: unknown) => void;
  handleIncomingMessage: (
    handle: string,
    space: FakeSpace,
    text: string,
  ) => Promise<void>;
  postImessageMessage: (
    handle: string,
    space: FakeSpace,
    text: string,
    messageId?: string,
  ) => Promise<void>;
  deliverOutbound: (destinationId: string, text: string) => Promise<void>;
  sendOutboundFile: (
    destinationId: string,
    file: Record<string, unknown>,
  ) => Promise<void>;
  imInstance: unknown;
  reactToMessage: (
    destinationId: string,
    platformMessageId: string,
    emoji: string,
    isChannel: boolean,
    replaces: string | null,
  ) => Promise<string>;
  adapterLogger: { warn: ReturnType<typeof vi.fn> };
  commands: Map<string, { execute: (p: unknown) => Promise<void> }>;
};

/** The fire-and-forget handlers a webhook message starts; settleInbound() awaits them. */
const INBOUND_HANDLERS = [
  "handleIncomingMessage",
  "handleMediaMessage",
  "handleMultiPartMessage",
] as const;
let inboundInFlight: Promise<void>[] = [];

function makeAdapter(): { adapter: ImessageAdapter; priv: PrivateAdapter } {
  const adapter = new ImessageAdapter();
  const priv = adapter as unknown as PrivateAdapter;
  priv.imInstance = {
    space: {
      create: vi.fn(async () => makeSpace()),
      get: vi.fn(async () => makeSpace()),
    },
    user: vi.fn(),
  };
  const handlers = adapter as unknown as Record<
    (typeof INBOUND_HANDLERS)[number],
    (...args: unknown[]) => Promise<void>
  >;
  for (const name of INBOUND_HANDLERS) {
    const handle = handlers[name].bind(adapter);
    handlers[name] = (...args) => {
      const handling = handle(...args);
      inboundInFlight.push(handling);
      return handling;
    };
  }
  return { adapter, priv };
}

/** Waits for every handler the webhook messages started, plus the contact card's direct send. */
async function settleInbound(): Promise<void> {
  await Promise.allSettled(inboundInFlight);
  await new Promise((resolve) => setImmediate(resolve));
}

/** Asserts postAndFollow received a request carrying these fields, a surface and an auth handler. */
function expectPosted(request: Record<string, unknown>): void {
  expect(postAndFollowSpy).toHaveBeenCalledWith(
    expect.objectContaining(request),
    expect.objectContaining({
      send: expect.any(Function),
      react: expect.any(Function),
      startTyping: expect.any(Function),
    }),
    expect.any(Function),
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  inboundInFlight = [];
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ImessageAdapter identity", () => {
  it("platform is imessage", () => {
    const { adapter } = makeAdapter();
    expect(adapter.platform).toBe("imessage");
  });
});

describe("sendImessageText", () => {
  it("sends via space.send and returns the message id", async () => {
    const { priv } = makeAdapter();
    const space = makeSpace();
    const sent = await priv.sendImessageText(space, "hi there");
    expect(space.send).toHaveBeenCalledWith("hi there");
    expect(sent.id).toBe("sent-1");
  });

  it("edit sends a new message instead of editing", async () => {
    const { priv } = makeAdapter();
    const space = makeSpace();
    const sent = await priv.sendImessageText(space, "first");
    await sent.edit("second");
    expect(space.send).toHaveBeenCalledTimes(2);
    expect(space.send).toHaveBeenLastCalledWith("second");
  });

  it("defaults id to empty string when send resolves undefined", async () => {
    const { priv } = makeAdapter();
    const space = makeSpace({ send: vi.fn(async () => undefined) });
    const sent = await priv.sendImessageText(space, "x");
    expect(sent.id).toBe("");
  });
});

describe("createImessageTarget", () => {
  it("exposes platform, userId, and channelId", () => {
    const { priv } = makeAdapter();
    const space = makeSpace();
    const target = priv.createImessageTarget("+15550100", space);
    expect(target.platform).toBe("imessage");
    expect(target.userId).toBe("+15550100");
    expect(target.channelId).toBe(space.id);
  });

  it("send and sendEphemeral both deliver to the space", async () => {
    const { priv } = makeAdapter();
    const space = makeSpace();
    const target = priv.createImessageTarget("+15550100", space);
    await target.send("a");
    await target.sendEphemeral("b");
    expect(space.send).toHaveBeenCalledTimes(2);
  });

  it("startTyping returns a callable no-op", async () => {
    const { priv } = makeAdapter();
    const target = priv.createImessageTarget("+15550100", makeSpace());
    const stop = await target.startTyping();
    expect(() => stop()).not.toThrow();
  });
});

describe("handleInboundMessage routing", () => {
  it("ignores outbound messages", async () => {
    const { priv } = makeAdapter();
    const space = makeSpace();
    priv.handleInboundMessage(space, makeMessage({ direction: "outbound" }));
    await settleInbound();
    expect(space.send).not.toHaveBeenCalled();
  });

  it("ignores messages without a sender", async () => {
    const { priv } = makeAdapter();
    const space = makeSpace();
    priv.handleInboundMessage(space, makeMessage({ sender: undefined }));
    await settleInbound();
    expect(space.send).not.toHaveBeenCalled();
  });

  it("ignores group spaces", async () => {
    const { priv } = makeAdapter();
    const space = makeSpace({ type: "group" });
    priv.handleInboundMessage(space, makeMessage());
    await settleInbound();
    expect(space.send).not.toHaveBeenCalled();
  });

  it("deduplicates redelivered message ids", async () => {
    const { priv } = makeAdapter();
    const space = makeSpace();
    const message = makeMessage({ content: { type: "text", text: "/help" } });
    priv.handleInboundMessage(space, message);
    await settleInbound();
    const sendsAfterFirst = space.send.mock.calls.length;
    priv.handleInboundMessage(space, message);
    await settleInbound();
    expect(space.send.mock.calls.length).toBe(sendsAfterFirst);
  });

  it("posts text messages with their message id", async () => {
    const { priv } = makeAdapter();
    const space = makeSpace();
    priv.handleInboundMessage(
      space,
      makeMessage({
        id: "msg-in",
        content: { type: "text", text: "what's up" },
      }),
    );
    await settleInbound();
    expectPosted({
      message: "what's up",
      platform: "imessage",
      platformUserId: "+15550100",
      channelId: space.id,
      isDm: true,
      platformMessageId: "msg-in",
    });
  });

  it("transcribes a standalone voice note instead of dropping it", async () => {
    const { adapter, priv } = makeAdapter();
    const space = makeSpace();
    const content = makeVoice();
    priv.handleInboundMessage(space, makeMessage({ content }));
    await settleInbound();

    const resolveMock = (
      adapter as unknown as { resolveIncomingMedia: ReturnType<typeof vi.fn> }
    ).resolveIncomingMedia;
    expect(resolveMock).toHaveBeenCalledTimes(1);
    expect(resolveMock.mock.calls[0][0]).toMatchObject({
      kind: "audio",
      isVoiceNote: true,
      mimeType: "audio/ogg",
      sizeBytes: 2048,
    });
    expect(space.send).not.toHaveBeenCalledWith(
      expect.stringContaining("I can't process"),
    );
  });

  it("tells the user when a media download stalls past the deadline", async () => {
    vi.useFakeTimers();
    try {
      const { adapter, priv } = makeAdapter();
      const space = makeSpace();
      let cancelled = false;
      const content = {
        ...makeAttachment(),
        stream: vi.fn(
          async () =>
            new ReadableStream<Uint8Array>({
              cancel() {
                cancelled = true;
              },
            }),
        ),
      };
      const resolveMock = (
        adapter as unknown as { resolveIncomingMedia: ReturnType<typeof vi.fn> }
      ).resolveIncomingMedia;
      resolveMock.mockImplementation(
        async (
          _media: unknown,
          download: (maxBytes: number) => Promise<Uint8Array>,
        ) => {
          await download(1024);
          return { action: "chat", text: "media", attachments: [] };
        },
      );

      priv.handleInboundMessage(space, makeMessage({ content }));
      await vi.advanceTimersByTimeAsync(MEDIA_READ_TIMEOUT_MS);
      vi.useRealTimers();
      await settleInbound();

      const sent = space.send.mock.calls.map((call) => call[0] as string);
      expect(sent).toContain(
        "That image took too long to download. Please try sending it again.",
      );
      expect(cancelled).toBe(true);
      expect(postAndFollowSpy).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("replies honestly when a voice note arrives without fetchable bytes", async () => {
    const { adapter, priv } = makeAdapter();
    const space = makeSpace();
    const content = makeVoice({ id: undefined });
    priv.handleInboundMessage(space, makeMessage({ content }));
    await settleInbound();

    const resolveMock = (
      adapter as unknown as { resolveIncomingMedia: ReturnType<typeof vi.fn> }
    ).resolveIncomingMedia;
    expect(resolveMock).not.toHaveBeenCalled();
    expect(content.stream).not.toHaveBeenCalled();
    expect(content.read).not.toHaveBeenCalled();

    const sent = space.send.mock.calls.map((call) => call[0] as string);
    expect(sent).toContain(
      "Voice notes aren't supported here yet. Please type your message instead.",
    );
    expect(sent.some((text) => text.includes("Something went wrong"))).toBe(
      false,
    );
  });

  it("reads a voice note through the same capped stream as an attachment", async () => {
    const { adapter, priv } = makeAdapter();
    const space = makeSpace();
    const content = makeVoice();
    priv.handleInboundMessage(space, makeMessage({ content }));
    await settleInbound();

    const resolveMock = (
      adapter as unknown as { resolveIncomingMedia: ReturnType<typeof vi.fn> }
    ).resolveIncomingMedia;
    const download = resolveMock.mock.calls[0][1] as (
      maxBytes: number,
    ) => Promise<Uint8Array>;

    const bytes = await download(CAP);

    expect(content.read).not.toHaveBeenCalled();
    expect(bytes.byteLength).toBe(CAP);
    expect(content.cancelled).toBe(true);
  });

  it("routes attachment content through resolveIncomingMedia", async () => {
    const { adapter, priv } = makeAdapter();
    const space = makeSpace();
    priv.handleInboundMessage(
      space,
      makeMessage({ content: makeAttachment() }),
    );
    await settleInbound();
    const resolveMock = (
      adapter as unknown as { resolveIncomingMedia: ReturnType<typeof vi.fn> }
    ).resolveIncomingMedia;
    expect(resolveMock).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "image", mimeType: "image/jpeg" }),
      expect.any(Function),
      "+15550100",
      space.id,
    );
  });

  it("forwards the attachment's declared size so an oversize file is rejected before any download", async () => {
    const { adapter, priv } = makeAdapter();
    const space = makeSpace();
    const content = makeAttachment({ size: 42_000_000 });
    priv.handleInboundMessage(space, makeMessage({ content }));
    await settleInbound();
    const resolveMock = (
      adapter as unknown as { resolveIncomingMedia: ReturnType<typeof vi.fn> }
    ).resolveIncomingMedia;
    expect(resolveMock.mock.calls[0][0]).toMatchObject({
      sizeBytes: 42_000_000,
    });
    expect(content.read).not.toHaveBeenCalled();
  });

  it("downloads through a capped stream instead of buffering the whole attachment", async () => {
    const { adapter, priv } = makeAdapter();
    const space = makeSpace();
    const content = makeAttachment();
    priv.handleInboundMessage(space, makeMessage({ content }));
    await settleInbound();
    const resolveMock = (
      adapter as unknown as { resolveIncomingMedia: ReturnType<typeof vi.fn> }
    ).resolveIncomingMedia;
    const download = resolveMock.mock.calls[0][1] as (
      maxBytes: number,
    ) => Promise<Uint8Array>;

    const bytes = await download(CAP);

    expect(content.read).not.toHaveBeenCalled();
    expect(bytes.byteLength).toBe(CAP);
    expect(content.produced).toBeLessThanOrEqual(CAP + 2 * ATTACHMENT_CHUNK);
    expect(content.cancelled).toBe(true);
  });
});

describe("multi-part (group) content", () => {
  function groupMessage(items: unknown[]) {
    return makeMessage({
      content: {
        type: "group",
        items: items.map((content, index) => ({ id: `p${index}`, content })),
      },
    });
  }

  function resolveMockOf(adapter: ImessageAdapter) {
    return (
      adapter as unknown as { resolveIncomingMedia: ReturnType<typeof vi.fn> }
    ).resolveIncomingMedia;
  }

  it("routes an attachment plus its caption through the media path", async () => {
    const { adapter, priv } = makeAdapter();
    const space = makeSpace();
    priv.handleInboundMessage(
      space,
      groupMessage([
        makeAttachment(),
        { type: "text", text: "explain this meme" },
      ]),
    );
    await settleInbound();

    const resolveMock = resolveMockOf(adapter);
    expect(resolveMock).toHaveBeenCalledTimes(1);
    expect(resolveMock.mock.calls[0][0]).toMatchObject({
      kind: "image",
      mimeType: "image/jpeg",
      caption: "explain this meme",
    });
    expect(space.send).not.toHaveBeenCalledWith(
      expect.stringContaining("I can't process"),
    );
  });

  it("routes a text-only multi-part message through the text path", async () => {
    const { adapter, priv } = makeAdapter();
    const space = makeSpace();
    priv.handleInboundMessage(
      space,
      groupMessage([
        { type: "text", text: "first line" },
        { type: "text", text: "second line" },
      ]),
    );
    await settleInbound();

    expect(resolveMockOf(adapter)).not.toHaveBeenCalled();
    expectPosted({ message: "first line\nsecond line" });
  });

  it("sends stacked images as ONE chat turn carrying every attachment", async () => {
    const { adapter, priv } = makeAdapter();
    const space = makeSpace();
    let uploaded = 0;
    resolveMockOf(adapter).mockImplementation(
      async (media: { caption?: string }) => {
        uploaded += 1;
        return {
          action: "chat" as const,
          text: media.caption ?? "media",
          attachments: [
            {
              fileId: `file-${uploaded}`,
              url: `https://cdn.gaia/${uploaded}`,
              filename: `photo-${uploaded}.jpg`,
              type: "file",
            },
          ],
        };
      },
    );

    priv.handleInboundMessage(
      space,
      groupMessage([
        makeAttachment(),
        makeAttachment(),
        makeAttachment(),
        { type: "text", text: "three pics" },
      ]),
    );
    await settleInbound();

    expect(resolveMockOf(adapter)).toHaveBeenCalledTimes(3);
    expect(postAndFollowSpy).toHaveBeenCalledTimes(1);
    expectPosted({
      message: "three pics",
      fileIds: ["file-1", "file-2", "file-3"],
    });
  });

  it("sends only the reply when no media part could be ingested", async () => {
    const { adapter, priv } = makeAdapter();
    const space = makeSpace();
    priv.handleInboundMessage(
      space,
      groupMessage([
        makeVoice({ id: undefined }),
        { type: "text", text: "listen to this" },
      ]),
    );
    await settleInbound();

    expect(resolveMockOf(adapter)).not.toHaveBeenCalled();
    const sent = space.send.mock.calls.map((call) => call[0] as string);
    expect(sent).toContain(
      "Voice notes aren't supported here yet. Please type your message instead.",
    );
    expect(postAndFollowSpy).not.toHaveBeenCalled();
  });

  it("replies about the part it actually received, never about groups", async () => {
    const { priv } = makeAdapter();
    const space = makeSpace();
    priv.handleInboundMessage(
      space,
      groupMessage([{ type: "contact", name: { first: "Ada" } }]),
    );
    await settleInbound();

    const sent = space.send.mock.calls[0][0] as string;
    expect(sent).toContain("contact cards");
    expect(sent).not.toContain("group");
  });

  it("routes a voice part inside a multi-part message with its caption", async () => {
    const { adapter, priv } = makeAdapter();
    const space = makeSpace();
    priv.handleInboundMessage(
      space,
      groupMessage([makeVoice(), { type: "text", text: "what did I say" }]),
    );
    await settleInbound();

    const resolveMock = resolveMockOf(adapter);
    expect(resolveMock).toHaveBeenCalledTimes(1);
    expect(resolveMock.mock.calls[0][0]).toMatchObject({
      kind: "audio",
      isVoiceNote: true,
      caption: "what did I say",
    });
    expect(postAndFollowSpy).toHaveBeenCalledTimes(1);
  });

  it("still replies unsupported for a standalone contact card", async () => {
    const { priv } = makeAdapter();
    const space = makeSpace();
    priv.handleInboundMessage(
      space,
      makeMessage({ content: { type: "contact", name: { first: "Ada" } } }),
    );
    await settleInbound();

    const sent = space.send.mock.calls[0][0] as string;
    expect(sent).toContain("contact cards");
  });
});

describe("handleIncomingMessage commands", () => {
  it("/gaia with text posts the rest", async () => {
    const { priv } = makeAdapter();
    const space = makeSpace();
    await priv.handleIncomingMessage("+15550100", space, "/gaia hello there");
    expectPosted({ message: "hello there" });
  });

  it("/gaia without text sends a usage hint", async () => {
    const { priv } = makeAdapter();
    const space = makeSpace();
    await priv.handleIncomingMessage("+15550100", space, "/gaia");
    expect(space.send).toHaveBeenCalledWith("Usage: /gaia <your message>");
    expect(postAndFollowSpy).not.toHaveBeenCalled();
  });

  it("unknown slash command replies via dispatchCommand", async () => {
    const { priv } = makeAdapter();
    const space = makeSpace();
    await priv.handleIncomingMessage("+15550100", space, "/nosuchcmd");
    expect(space.send).toHaveBeenCalledWith("Unknown command: /nosuchcmd");
  });

  it("starts and stops the typing indicator", async () => {
    const { priv } = makeAdapter();
    const space = makeSpace();
    await priv.handleIncomingMessage("+15550100", space, "hello");
    expect(space.startTyping).toHaveBeenCalled();
    expect(space.stopTyping).toHaveBeenCalled();
  });
});

describe("outbound delivery", () => {
  it("deliverOutbound resolves the space from the handle and sends", async () => {
    const { priv } = makeAdapter();
    const outSpace = makeSpace();
    const create = vi.fn(async () => outSpace);
    priv.imInstance = { space: { create, get: vi.fn() }, user: vi.fn() };
    await priv.deliverOutbound("+15550100", "reminder text");
    expect(create).toHaveBeenCalledWith("+15550100");
    expect(outSpace.send).toHaveBeenCalledWith("reminder text");
  });

  it("sendOutboundFile sends an attachment built from the artifact", async () => {
    const { priv } = makeAdapter();
    const outSpace = makeSpace();
    priv.imInstance = {
      space: { create: vi.fn(async () => outSpace), get: vi.fn() },
      user: vi.fn(),
    };
    await priv.sendOutboundFile("+15550100", {
      data: Buffer.from([1, 2, 3]),
      mime: "application/pdf",
      filename: "report.pdf",
      caption: undefined,
    });
    expect(attachment).toHaveBeenCalledWith(expect.any(Buffer), {
      name: "report.pdf",
      mimeType: "application/pdf",
    });
    expect(outSpace.send).toHaveBeenCalledTimes(1);
  });
});

describe("reactToMessage", () => {
  function setup(space = makeSpace()) {
    const { priv } = makeAdapter();
    const create = vi.fn(async () => space);
    priv.imInstance = { space: { create, get: vi.fn() }, user: vi.fn() };
    return { priv, space, create };
  }

  it("resolves the target in the destination's space and sends a reaction to it", async () => {
    const { priv, space, create } = setup();

    const outcome = await priv.reactToMessage(
      "+15550100",
      "msg-9",
      "👍",
      false,
      null,
    );

    expect(outcome).toBe("attached");
    expect(create).toHaveBeenCalledWith("+15550100");
    expect(space.getMessage).toHaveBeenCalledWith("msg-9");
    expect(reaction).toHaveBeenCalledWith("👍", { id: "msg-9" });
    expect(space.send).toHaveBeenCalledWith(
      expect.objectContaining({
        __reaction: { emoji: "👍", target: { id: "msg-9" } },
      }),
    );
  });

  it("passes an emoji outside the six classic tapbacks through unchanged", async () => {
    const { priv, space } = setup();

    const outcome = await priv.reactToMessage(
      "+15550100",
      "msg-9",
      "🫡",
      false,
      null,
    );

    expect(outcome).toBe("attached");
    expect(reaction).toHaveBeenCalledWith("🫡", { id: "msg-9" });
    expect(space.send).toHaveBeenCalledTimes(1);
  });

  it("reports attach_failed and logs when the platform skips the reaction", async () => {
    const space = makeSpace({ send: vi.fn(async () => undefined) });
    const { priv } = setup(space);

    const outcome = await priv.reactToMessage(
      "+15550100",
      "msg-9",
      "👍",
      false,
      null,
    );

    expect(outcome).toBe("attach_failed");
    expect(priv.adapterLogger.warn).toHaveBeenCalledWith(
      "outbound_reaction_unsupported_by_platform",
      { target_platform_message_id: "msg-9" },
    );
  });

  it("reports attach_failed and logs the error when the SDK throws", async () => {
    const space = makeSpace({
      send: vi.fn(async () => {
        throw new Error("photon down");
      }),
    });
    const { priv } = setup(space);

    const outcome = await priv.reactToMessage(
      "+15550100",
      "msg-9",
      "👍",
      false,
      null,
    );

    expect(outcome).toBe("attach_failed");
    expect(priv.adapterLogger.warn).toHaveBeenCalledWith(
      "outbound_reaction_attach_failed",
      { error_type: "Error", error: "photon down" },
    );
  });

  it("reports attach_failed without sending when the target message is not found", async () => {
    const space = makeSpace({ getMessage: vi.fn(async () => undefined) });
    const { priv } = setup(space);

    const outcome = await priv.reactToMessage(
      "+15550100",
      "gone",
      "👍",
      false,
      null,
    );

    expect(outcome).toBe("attach_failed");
    expect(space.send).not.toHaveBeenCalled();
    expect(priv.adapterLogger.warn).toHaveBeenCalledWith(
      "outbound_reaction_target_not_found",
      { target_platform_message_id: "gone" },
    );
  });
});

describe("postImessageMessage", () => {
  it("sends help text for an empty message and does not post", async () => {
    const { priv } = makeAdapter();
    const space = makeSpace();

    await priv.postImessageMessage("+15550100", space, "   ", "msg-in");

    expect(space.send).toHaveBeenCalledWith(
      expect.stringContaining("Hi! Send me a message"),
    );
    expect(postAndFollowSpy).not.toHaveBeenCalled();
  });

  it("the auth handler sends the shared auth-link message into the space", async () => {
    const { priv } = makeAdapter();
    const space = makeSpace();
    await priv.postImessageMessage("+15550100", space, "hi", "msg-in");

    await lastAuthHandler()("https://auth.example.com/link");

    expect(space.send).toHaveBeenCalledTimes(1);
    const body = space.send.mock.calls[0][0] as string;
    expect(body).toContain("https://auth.example.com/link");
    expect(body).toContain("Link your account to GAIA");
  });
});

describe("conversation surface", () => {
  /** Posts one message into a space and returns the surface handed to postAndFollow. */
  async function surfaceFor(space: FakeSpace) {
    const { priv } = makeAdapter();
    priv.imInstance = {
      space: { create: vi.fn(async () => space), get: vi.fn() },
      user: vi.fn(),
    };
    await priv.postImessageMessage("+15550100", space, "hi", "msg-in");
    return { priv, surface: lastSurface() };
  }

  it("sends a threaded reply to the message it answers", async () => {
    const space = makeSpace();
    const { surface } = await surfaceFor(space);

    await surface.send("on it", "msg-earlier");

    expect(space.getMessage).toHaveBeenCalledWith("msg-earlier");
    expect(reply).toHaveBeenCalledWith("on it", { id: "msg-earlier" });
    expect(space.send).toHaveBeenCalledWith(
      expect.objectContaining({
        __reply: { text: "on it", target: { id: "msg-earlier" } },
      }),
    );
  });

  it("sends plain text, logging the miss, when the message it answers is gone", async () => {
    const space = makeSpace({ getMessage: vi.fn(async () => undefined) });
    const { priv, surface } = await surfaceFor(space);

    await surface.send("on it", "msg-gone");

    expect(reply).not.toHaveBeenCalled();
    expect(space.send).toHaveBeenCalledWith("on it");
    expect(priv.adapterLogger.warn).toHaveBeenCalledWith(
      "reply_target_not_found",
      { target_platform_message_id: "msg-gone" },
    );
  });

  it("sends plain text without a lookup when there is nothing to reply to", async () => {
    const space = makeSpace();
    const { surface } = await surfaceFor(space);

    await surface.send("here you go", null);

    expect(space.getMessage).not.toHaveBeenCalled();
    expect(space.send).toHaveBeenCalledWith("here you go");
  });

  it("a sent message's edit sends a new message, and it offers no delete", async () => {
    const space = makeSpace();
    const { surface } = await surfaceFor(space);
    const sent = await surface.send("first", null);

    await sent.edit("second");

    expect(space.send).toHaveBeenLastCalledWith("second");
    expect(sent.delete).toBeUndefined();
  });

  it("reacts to the given message in the user's space", async () => {
    const space = makeSpace();
    const { priv, surface } = await surfaceFor(space);
    const react = vi.spyOn(priv, "reactToMessage");

    expect(await surface.react("msg-in", "👍", "🔎")).toBe("attached");
    expect(react).toHaveBeenCalledWith(
      "+15550100",
      "msg-in",
      "👍",
      false,
      "🔎",
    );
    expect(reaction).toHaveBeenCalledWith("👍", { id: "msg-in" });
  });

  it("starts typing in the space and the returned function stops it", async () => {
    const space = makeSpace();
    const { surface } = await surfaceFor(space);

    const stopTyping = surface.startTyping();
    expect(space.startTyping).toHaveBeenCalledTimes(1);
    expect(space.stopTyping).not.toHaveBeenCalled();

    stopTyping();
    expect(space.stopTyping).toHaveBeenCalledTimes(1);
  });
});

describe("inbound order", () => {
  /** An adapter whose first welcome auth check hangs until releaseFirst() — the interleaving that reordered posts. */
  function heldInWelcome() {
    const { priv } = makeAdapter();
    const space = makeSpace();
    let releaseFirst = (): void => undefined;
    const checkAuthStatus = vi.fn().mockReturnValueOnce(
      new Promise((resolve) => {
        releaseFirst = () => resolve({ authenticated: true });
      }),
    );
    (priv as unknown as { gaia: unknown }).gaia = {
      checkAuthStatus,
      getPricingUrl: () => "https://gaia.test/pricing",
    };
    const deliver = (text: string) =>
      priv.handleInboundMessage(
        space,
        makeMessage({ content: { type: "text", text } }),
      );
    return {
      priv,
      deliver,
      checkAuthStatus,
      releaseFirst: () => releaseFirst(),
    };
  }

  it("posts a sender's messages in arrival order when the first is held in its welcome check", async () => {
    const { deliver, checkAuthStatus, releaseFirst } = heldInWelcome();

    deliver("do the work");
    await vi.waitFor(() => expect(checkAuthStatus).toHaveBeenCalledTimes(1));
    deliver("and then");
    await new Promise((resolve) => setImmediate(resolve));

    // The second message is ready first, but its post waits for the first's.
    expect(postAndFollowSpy).not.toHaveBeenCalled();

    releaseFirst();
    await settleInbound();
    expect(postAndFollowSpy.mock.calls.map(([req]) => req.message)).toEqual([
      "do the work",
      "and then",
    ]);
  });

  it("dispatches a /stop behind a held message without waiting for it", async () => {
    const { priv, deliver, checkAuthStatus, releaseFirst } = heldInWelcome();
    const stopExecute = vi.fn().mockResolvedValue(undefined);
    priv.commands.set("stop", { execute: stopExecute });

    deliver("do the work");
    await vi.waitFor(() => expect(checkAuthStatus).toHaveBeenCalledTimes(1));
    deliver("/stop");

    await vi.waitFor(() => expect(stopExecute).toHaveBeenCalledTimes(1));
    expect(postAndFollowSpy).not.toHaveBeenCalled();

    releaseFirst();
    await settleInbound();
    expect(postAndFollowSpy).toHaveBeenCalledTimes(1);
  });
});

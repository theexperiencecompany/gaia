import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("spectrum-ts", () => ({
  Spectrum: vi.fn(),
  attachment: vi.fn((input: unknown, options: unknown) => ({
    __attachment: { input, options },
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

vi.mock("@gaia/shared", async () => {
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

import { handleStreamingChat, MEDIA_READ_TIMEOUT_MS } from "@gaia/shared";
import { attachment } from "spectrum-ts";
import { ImessageAdapter } from "../../imessage/src/adapter";

interface FakeSpace {
  id: string;
  type: "dm" | "group";
  send: ReturnType<typeof vi.fn>;
  startTyping: ReturnType<typeof vi.fn>;
  stopTyping: ReturnType<typeof vi.fn>;
}

function makeSpace(overrides: Partial<FakeSpace> = {}): FakeSpace {
  return {
    id: "any;-;+15550100",
    type: "dm",
    send: vi.fn(async () => ({ id: "sent-1" })),
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
  handleStreamingMessage: (
    handle: string,
    space: FakeSpace,
    text: string,
  ) => Promise<void>;
  messageQueues: Map<string, Promise<void>>;
  deliverOutbound: (destinationId: string, text: string) => Promise<void>;
  deliverOutboundFile: (
    destinationId: string,
    a: Record<string, unknown>,
  ) => Promise<void>;
  fetchOutboundArtifact: ReturnType<typeof vi.fn>;
  imInstance: unknown;
  commands: Map<string, { execute: (p: unknown) => Promise<void> }>;
};

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
  return { adapter, priv };
}

async function drainQueues(priv: PrivateAdapter): Promise<void> {
  await Promise.all([...priv.messageQueues.values()]);
  await new Promise((resolve) => setImmediate(resolve));
}

beforeEach(() => {
  vi.clearAllMocks();
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
    await drainQueues(priv);
    expect(space.send).not.toHaveBeenCalled();
  });

  it("ignores messages without a sender", async () => {
    const { priv } = makeAdapter();
    const space = makeSpace();
    priv.handleInboundMessage(space, makeMessage({ sender: undefined }));
    await drainQueues(priv);
    expect(space.send).not.toHaveBeenCalled();
  });

  it("ignores group spaces", async () => {
    const { priv } = makeAdapter();
    const space = makeSpace({ type: "group" });
    priv.handleInboundMessage(space, makeMessage());
    await drainQueues(priv);
    expect(space.send).not.toHaveBeenCalled();
  });

  it("deduplicates redelivered message ids", async () => {
    const { priv } = makeAdapter();
    const space = makeSpace();
    const message = makeMessage({ content: { type: "text", text: "/help" } });
    priv.handleInboundMessage(space, message);
    await drainQueues(priv);
    const sendsAfterFirst = space.send.mock.calls.length;
    priv.handleInboundMessage(space, message);
    await drainQueues(priv);
    expect(space.send.mock.calls.length).toBe(sendsAfterFirst);
  });

  it("routes text messages into the streaming chat pipeline", async () => {
    const { priv } = makeAdapter();
    const space = makeSpace();
    priv.handleInboundMessage(
      space,
      makeMessage({ content: { type: "text", text: "what's up" } }),
    );
    await drainQueues(priv);
    expect(handleStreamingChat).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({
        message: "what's up",
        platform: "imessage",
        platformUserId: "+15550100",
        channelId: space.id,
      }),
      expect.anything(),
      expect.anything(),
      expect.anything(),
      expect.anything(),
      expect.anything(),
      undefined,
    );
  });

  it("transcribes a standalone voice note instead of dropping it", async () => {
    const { adapter, priv } = makeAdapter();
    const space = makeSpace();
    const content = makeVoice();
    priv.handleInboundMessage(space, makeMessage({ content }));
    await drainQueues(priv);

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
      await drainQueues(priv);

      const sent = space.send.mock.calls.map((call) => call[0] as string);
      expect(sent).toContain(
        "That image took too long to download. Please try sending it again.",
      );
      expect(cancelled).toBe(true);
      expect(handleStreamingChat).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("replies honestly when a voice note arrives without fetchable bytes", async () => {
    const { adapter, priv } = makeAdapter();
    const space = makeSpace();
    const content = makeVoice({ id: undefined });
    priv.handleInboundMessage(space, makeMessage({ content }));
    await drainQueues(priv);

    const resolveMock = (
      adapter as unknown as { resolveIncomingMedia: ReturnType<typeof vi.fn> }
    ).resolveIncomingMedia;
    expect(resolveMock).not.toHaveBeenCalled();
    expect(content.stream).not.toHaveBeenCalled();
    expect(content.read).not.toHaveBeenCalled();

    const sent = space.send.mock.calls.map((call) => call[0] as string);
    expect(sent).toContain(
      "Voice notes aren't supported here yet — please type your message instead.",
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
    await drainQueues(priv);

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
    await drainQueues(priv);
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
    await drainQueues(priv);
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
    await drainQueues(priv);
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
    await drainQueues(priv);

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
    await drainQueues(priv);

    expect(resolveMockOf(adapter)).not.toHaveBeenCalled();
    expect(handleStreamingChat).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ message: "first line\nsecond line" }),
      expect.anything(),
      expect.anything(),
      expect.anything(),
      expect.anything(),
      expect.anything(),
      undefined,
    );
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
    await drainQueues(priv);

    expect(resolveMockOf(adapter)).toHaveBeenCalledTimes(3);
    expect(handleStreamingChat).toHaveBeenCalledTimes(1);
    expect(handleStreamingChat).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({
        message: "three pics",
        fileIds: ["file-1", "file-2", "file-3"],
      }),
      expect.anything(),
      expect.anything(),
      expect.anything(),
      expect.anything(),
      expect.anything(),
      undefined,
    );
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
    await drainQueues(priv);

    expect(resolveMockOf(adapter)).not.toHaveBeenCalled();
    const sent = space.send.mock.calls.map((call) => call[0] as string);
    expect(sent).toContain(
      "Voice notes aren't supported here yet — please type your message instead.",
    );
    expect(handleStreamingChat).not.toHaveBeenCalled();
  });

  it("replies about the part it actually received, never about groups", async () => {
    const { priv } = makeAdapter();
    const space = makeSpace();
    priv.handleInboundMessage(
      space,
      groupMessage([{ type: "contact", name: { first: "Ada" } }]),
    );
    await drainQueues(priv);

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
    await drainQueues(priv);

    const resolveMock = resolveMockOf(adapter);
    expect(resolveMock).toHaveBeenCalledTimes(1);
    expect(resolveMock.mock.calls[0][0]).toMatchObject({
      kind: "audio",
      isVoiceNote: true,
      caption: "what did I say",
    });
    expect(handleStreamingChat).toHaveBeenCalledTimes(1);
  });

  it("still replies unsupported for a standalone contact card", async () => {
    const { priv } = makeAdapter();
    const space = makeSpace();
    priv.handleInboundMessage(
      space,
      makeMessage({ content: { type: "contact", name: { first: "Ada" } } }),
    );
    await drainQueues(priv);

    const sent = space.send.mock.calls[0][0] as string;
    expect(sent).toContain("contact cards");
  });
});

describe("handleIncomingMessage commands", () => {
  it("/gaia with text streams the rest", async () => {
    const { priv } = makeAdapter();
    const space = makeSpace();
    await priv.handleIncomingMessage("+15550100", space, "/gaia hello there");
    expect(handleStreamingChat).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ message: "hello there" }),
      expect.anything(),
      expect.anything(),
      expect.anything(),
      expect.anything(),
      expect.anything(),
      undefined,
    );
  });

  it("/gaia without text sends a usage hint", async () => {
    const { priv } = makeAdapter();
    const space = makeSpace();
    await priv.handleIncomingMessage("+15550100", space, "/gaia");
    expect(space.send).toHaveBeenCalledWith("Usage: /gaia <your message>");
    expect(handleStreamingChat).not.toHaveBeenCalled();
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

  it("deliverOutboundFile sends an attachment built from the artifact", async () => {
    const { priv } = makeAdapter();
    const outSpace = makeSpace();
    priv.imInstance = {
      space: { create: vi.fn(async () => outSpace), get: vi.fn() },
      user: vi.fn(),
    };
    priv.fetchOutboundArtifact = vi.fn(async () => ({
      data: new Uint8Array([1, 2, 3]),
      contentType: "application/pdf",
    }));
    await priv.deliverOutboundFile("+15550100", {
      filename: "report.pdf",
      content_type: "application/pdf",
    });
    expect(attachment).toHaveBeenCalledWith(expect.any(Buffer), {
      name: "report.pdf",
      mimeType: "application/pdf",
    });
    expect(outSpace.send).toHaveBeenCalledTimes(1);
  });
});

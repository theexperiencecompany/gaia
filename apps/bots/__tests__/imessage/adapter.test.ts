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
      unsupportedMediaMessage: vi.fn(real.unsupportedMediaMessage),
      mediaKindFromMime: vi.fn(real.mediaKindFromMime),
      readBodyBytesBounded: vi.fn(real.readBodyBytesBounded),
      BODY_TOO_LARGE: real.BODY_TOO_LARGE,
      BODY_READ_TIMEOUT: real.BODY_READ_TIMEOUT,
      WEBHOOK_MAX_BODY_BYTES: real.WEBHOOK_MAX_BODY_BYTES,
    },
  });
});

import { handleStreamingChat } from "@gaia/shared";
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

  it("routes attachment content through resolveIncomingMedia", async () => {
    const { adapter, priv } = makeAdapter();
    const space = makeSpace();
    const read = vi.fn(async () => Buffer.from("bytes"));
    priv.handleInboundMessage(
      space,
      makeMessage({
        content: {
          type: "attachment",
          id: "att-1",
          name: "photo.jpg",
          mimeType: "image/jpeg",
          read,
        },
      }),
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

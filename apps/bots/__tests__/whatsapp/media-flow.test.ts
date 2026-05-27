/**
 * Adapter-level tests for the WhatsApp media pipeline.
 *
 * The transcribe-vs-upload-vs-reject decision now lives in the SHARED
 * {@link processBotMedia} (covered exhaustively in __tests__/shared/utils/media.test.ts).
 * These tests therefore cover only the ADAPTER's own responsibilities around
 * {@link WhatsAppAdapter.handleMediaMessage}:
 *
 * 1. It maps a Kapso media descriptor onto an {@link IncomingMedia} shape and
 *    calls resolveIncomingMedia with a working download thunk.
 * 2. A "chat" outcome is dispatched to handleStreamingChat with fileIds/fileData.
 * 3. A "reply" outcome is sent verbatim via sendWhatsAppText.
 * 4. The download thunk actually downloads the right Kapso media bytes.
 * 5. A thrown error from the shared pipeline produces a friendlyMediaError reply.
 *
 * Only the boundaries are mocked: the Kapso WhatsApp client and @gaia/shared
 * (via the shared mock factory). The real friendlyMediaError copy is wired into
 * the mock so the error-path assertions exercise production strings.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  friendlyMediaError,
  unsupportedMediaMessage,
} from "../../../../libs/shared/ts/src/bots/utils";

// ---------------------------------------------------------------------------
// Mocks — must run before importing the adapter so they take effect.
// ---------------------------------------------------------------------------

const mockSendText = vi.fn();
const mockMarkRead = vi.fn();
const mockMediaDownload = vi.fn();

const mockWaClientInstance = {
  messages: {
    sendText: mockSendText,
    markRead: mockMarkRead,
  },
  media: {
    download: mockMediaDownload,
  },
};

vi.mock("@kapso/whatsapp-cloud-api", () => ({
  WhatsAppClient: vi.fn().mockImplementation(() => mockWaClientInstance),
}));

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
  // Wire the REAL pure helpers the adapter imports so the error/unsupported
  // paths assert production copy, not a stub.
  const real = await import("../../../../libs/shared/ts/src/bots/utils");
  return makeGaiaSharedMock("whatsapp", {
    streamingDefaults: {
      whatsapp: {
        editIntervalMs: 2000,
        streaming: false,
        platform: "whatsapp",
      },
    },
    converters: {
      friendlyMediaError: vi.fn(real.friendlyMediaError),
      unsupportedMediaMessage: vi.fn(real.unsupportedMediaMessage),
      extractSubcommandArgs: vi.fn(real.extractSubcommandArgs),
    },
    defaultRichMarkdown: "*GAIA Help*\nUse /gaia to chat",
  });
});

// ---------------------------------------------------------------------------
// Imports — happen after mocks so the adapter picks them up.
// ---------------------------------------------------------------------------

import { handleStreamingChat } from "@gaia/shared";
import { WhatsAppAdapter } from "../../whatsapp/src/adapter";
import type { ExtractedMedia } from "../../whatsapp/src/webhook.types";

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

const WA_ID = "15551234567";
const MOCK_CONFIG = {
  kapsoApiKey: "test-api-key", // pragma: allowlist secret
  kapsoPhoneNumberId: "test-phone-id",
  kapsoWebhookSecret: "test-secret", // pragma: allowlist secret
};

/** Outcome returned by the shared media pipeline (overridable per-test). */
type MediaOutcome =
  | {
      action: "chat";
      text: string;
      attachments: {
        fileId: string;
        url: string;
        filename: string;
        type: string;
      }[];
    }
  | { action: "reply"; text: string };

interface MediaInternals {
  waClient: typeof mockWaClientInstance;
  waConfig: typeof MOCK_CONFIG;
  linkedUsers: Set<string>;
  welcomeSent: Set<string>;
  resolveIncomingMedia: ReturnType<typeof vi.fn>;
}

function buildAdapter(): WhatsAppAdapter {
  const adapter = new WhatsAppAdapter();
  const inner = adapter as unknown as MediaInternals;
  inner.waClient = mockWaClientInstance;
  inner.waConfig = MOCK_CONFIG;
  // Skip the welcome gate so these tests focus on media routing only.
  inner.linkedUsers = new Set([WA_ID]);
  inner.welcomeSent = new Set([WA_ID]);
  return adapter;
}

/** Stubs the shared resolveIncomingMedia outcome for the next call. */
function setOutcome(adapter: WhatsAppAdapter, outcome: MediaOutcome): void {
  (
    adapter as unknown as MediaInternals
  ).resolveIncomingMedia.mockResolvedValueOnce(outcome);
}

function resolveCalls(adapter: WhatsAppAdapter): ReturnType<typeof vi.fn> {
  return (adapter as unknown as MediaInternals).resolveIncomingMedia;
}

function media(overrides: Partial<ExtractedMedia>): ExtractedMedia {
  return {
    kind: "image",
    isVoiceNote: false,
    mediaId: "wa-media-1",
    mimeType: "image/jpeg",
    ...overrides,
  };
}

function callHandle(
  adapter: WhatsAppAdapter,
  m: ExtractedMedia,
  messageId = "wamid.test",
): Promise<void> {
  return (
    adapter as unknown as {
      handleMediaMessage: (
        waId: string,
        media: ExtractedMedia,
        messageId: string,
      ) => Promise<void>;
    }
  ).handleMediaMessage(WA_ID, m, messageId);
}

function lastSentBody(): string {
  const call = mockSendText.mock.calls.at(-1);
  return (call?.[0] as { body: string }).body;
}

function getChatRequest(): {
  message: string;
  fileIds?: string[];
  fileData?: { fileId: string; url: string }[];
  platform: string;
  platformUserId: string;
} {
  const mocked = vi.mocked(handleStreamingChat);
  return mocked.mock.calls.at(-1)![1] as ReturnType<typeof getChatRequest>;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("WhatsAppAdapter - media routing", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSendText.mockResolvedValue({ messages: [{ id: "sent-msg" }] });
    mockMarkRead.mockResolvedValue(undefined);
    mockMediaDownload.mockResolvedValue(new Uint8Array([1, 2, 3, 4, 5]).buffer);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("builds an IncomingMedia descriptor from the Kapso media for an image with a caption", async () => {
    const adapter = buildAdapter();
    setOutcome(adapter, { action: "chat", text: "x", attachments: [] });

    await callHandle(
      adapter,
      media({
        kind: "image",
        mediaId: "wa-media-image",
        mimeType: "image/png",
        caption: "what's in this picture?",
        filename: "photo.png",
      }),
    );

    expect(resolveCalls(adapter)).toHaveBeenCalledTimes(1);
    const incoming = resolveCalls(adapter).mock.calls[0][0];
    expect(incoming).toMatchObject({
      kind: "image",
      isVoiceNote: false,
      mimeType: "image/png",
      filename: "photo.png",
      caption: "what's in this picture?",
    });
  });

  it("preserves the voice-note flag and audio mime type in the descriptor", async () => {
    const adapter = buildAdapter();
    setOutcome(adapter, { action: "chat", text: "x", attachments: [] });

    await callHandle(
      adapter,
      media({
        kind: "audio",
        isVoiceNote: true,
        mediaId: "wa-media-voice",
        mimeType: "audio/ogg",
      }),
    );

    const incoming = resolveCalls(adapter).mock.calls[0][0];
    expect(incoming).toMatchObject({
      kind: "audio",
      isVoiceNote: true,
      mimeType: "audio/ogg",
    });
  });

  it("passes a download thunk that fetches the correct Kapso media bytes", async () => {
    const adapter = buildAdapter();
    setOutcome(adapter, { action: "chat", text: "x", attachments: [] });

    await callHandle(
      adapter,
      media({ mediaId: "wa-media-download", mimeType: "image/png" }),
    );

    // The adapter must hand resolveIncomingMedia a thunk, not pre-downloaded
    // bytes — unsupported kinds must be able to skip the download entirely.
    const thunk = resolveCalls(adapter).mock
      .calls[0][1] as () => Promise<Uint8Array>;
    expect(mockMediaDownload).not.toHaveBeenCalled();

    const bytes = await thunk();
    expect(mockMediaDownload).toHaveBeenCalledWith({
      mediaId: "wa-media-download",
      phoneNumberId: "test-phone-id",
    });
    expect(bytes).toBeInstanceOf(Uint8Array);
    expect(Array.from(bytes)).toEqual([1, 2, 3, 4, 5]);
  });

  it("dispatches a 'chat' outcome to handleStreamingChat with fileIds and fileData", async () => {
    const adapter = buildAdapter();
    setOutcome(adapter, {
      action: "chat",
      text: "Please describe this image.",
      attachments: [
        {
          fileId: "file-1",
          url: "https://cdn.example/photo.png",
          filename: "photo.png",
          type: "image/png",
        },
      ],
    });

    await callHandle(adapter, media({ kind: "image", mimeType: "image/png" }));

    expect(handleStreamingChat).toHaveBeenCalledTimes(1);
    const req = getChatRequest();
    expect(req.platform).toBe("whatsapp");
    expect(req.platformUserId).toBe(WA_ID);
    expect(req.message).toBe("Please describe this image.");
    expect(req.fileIds).toEqual(["file-1"]);
    expect(req.fileData![0].url).toBe("https://cdn.example/photo.png");
    expect(mockSendText).not.toHaveBeenCalled();
  });

  it("dispatches a transcript 'chat' outcome with no attachments", async () => {
    const adapter = buildAdapter();
    setOutcome(adapter, {
      action: "chat",
      text: "this is the transcribed voice note",
      attachments: [],
    });

    await callHandle(
      adapter,
      media({ kind: "audio", isVoiceNote: true, mimeType: "audio/ogg" }),
    );

    const req = getChatRequest();
    expect(req.message).toBe("this is the transcribed voice note");
    expect(req.fileIds).toBeUndefined();
    expect(req.fileData).toBeUndefined();
  });

  it("sends a 'reply' outcome verbatim and does NOT start a chat turn", async () => {
    const adapter = buildAdapter();
    setOutcome(adapter, {
      action: "reply",
      text: "That file is too large to process (limit: 10 MB). Please share a smaller file.",
    });

    await callHandle(adapter, media({ kind: "image", mimeType: "image/png" }));

    expect(handleStreamingChat).not.toHaveBeenCalled();
    expect(lastSentBody()).toBe(
      "That file is too large to process (limit: 10 MB). Please share a smaller file.",
    );
  });

  it("replies with a friendly media error when the shared pipeline throws", async () => {
    const adapter = buildAdapter();
    const err = Object.assign(new Error("API error: 401"), { status: 401 });
    (
      adapter as unknown as MediaInternals
    ).resolveIncomingMedia.mockRejectedValueOnce(err);

    await callHandle(adapter, media({ kind: "image", mimeType: "image/png" }));

    expect(handleStreamingChat).not.toHaveBeenCalled();
    // friendlyMediaError("image", 401) → link-account copy.
    expect(lastSentBody()).toBe(friendlyMediaError("image", err));
    expect(lastSentBody()).toMatch(/link your GAIA account/i);
  });

  it("maps a 413 failure to the too-large reply via friendlyMediaError", async () => {
    const adapter = buildAdapter();
    const err = Object.assign(new Error("API error: 413"), { status: 413 });
    (
      adapter as unknown as MediaInternals
    ).resolveIncomingMedia.mockRejectedValueOnce(err);

    await callHandle(
      adapter,
      media({ kind: "document", mimeType: "application/pdf" }),
    );

    expect(lastSentBody()).toBe(friendlyMediaError("document", err));
    expect(lastSentBody()).toMatch(/too large/i);
  });
});

// ---------------------------------------------------------------------------
// Unsupported / unparseable media — driven through the real webhook router.
// When extractMedia returns null (unknown type, or media without an id) the
// adapter must reply with unsupportedMediaMessage(type) and never touch the
// shared pipeline or download anything.
// ---------------------------------------------------------------------------

/** Builds a Kapso event with a fresh timestamp so the replay guard accepts it. */
function kapsoEvent(over: {
  type: string;
  body?: Record<string, unknown>;
}): unknown {
  return {
    message: {
      id: "wamid.unsupported",
      timestamp: String(Math.floor(Date.now() / 1000)),
      type: over.type,
      ...over.body,
    },
    conversation: {
      id: "conv-1",
      phone_number: `+${WA_ID}`,
      phone_number_id: "test-phone-id",
      status: "active",
    },
    phone_number_id: "test-phone-id",
  };
}

/** Drives a single event through the private webhook router. */
function routeEvent(adapter: WhatsAppAdapter, event: unknown): void {
  (
    adapter as unknown as {
      handleWebhookEvent: (event: unknown) => void;
    }
  ).handleWebhookEvent(event);
}

/** Lets the per-user queue drain so async handlers have run. */
async function flushQueue(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

describe("WhatsAppAdapter - unsupported media (extractMedia returns null)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSendText.mockResolvedValue({ messages: [{ id: "sent-msg" }] });
    mockMediaDownload.mockResolvedValue(new Uint8Array([1, 2, 3]).buffer);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("replies with unsupportedMediaMessage for an unknown message type", async () => {
    const adapter = buildAdapter();

    routeEvent(
      adapter,
      kapsoEvent({ type: "contacts", body: { contacts: [] } }),
    );
    await flushQueue();

    expect(lastSentBody()).toBe(unsupportedMediaMessage("contacts"));
    expect(lastSentBody()).toMatch(/contacts messages/i);
    expect(handleStreamingChat).not.toHaveBeenCalled();
    expect(mockMediaDownload).not.toHaveBeenCalled();
  });

  it("replies with unsupportedMediaMessage when a media payload lacks an id", async () => {
    const adapter = buildAdapter();

    // image payload without `id` → extractMedia returns null → unsupported path.
    routeEvent(
      adapter,
      kapsoEvent({
        type: "image",
        body: { image: { mime_type: "image/png" } },
      }),
    );
    await flushQueue();

    expect(lastSentBody()).toBe(unsupportedMediaMessage("image"));
    expect(handleStreamingChat).not.toHaveBeenCalled();
    expect(mockMediaDownload).not.toHaveBeenCalled();
  });
});

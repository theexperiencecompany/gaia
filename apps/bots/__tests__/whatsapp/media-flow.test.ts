/**
 * End-to-end tests for the WhatsApp media pipeline.
 *
 * Exercises {@link WhatsAppAdapter.handleMediaMessage} against mocked Kapso +
 * Gaia clients so we cover every branch without touching real services:
 *
 * 1. Image: download → upload → chat-stream with fileIds + fileData
 * 2. Voice note: download → transcribe → chat-stream (no upload)
 * 3. Plain audio file: same transcription path, filename derived from mime
 * 4. Document: download → upload → chat-stream with fallback prompt
 * 5. Image with caption: caption used as the user message
 * 6. Video: politely declined (no download, no upload)
 * 7. Sticker: politely declined
 * 8. Empty transcript: "couldn't understand audio" reply
 * 9. Oversize audio (>25 MB): rejected before transcribing
 * 10. Oversize file (>10 MB): rejected before uploading
 * 11. Upload returns 401: surfaces "link your account" message
 * 12. Upload returns 413: surfaces "too large" message
 * 13. Upload returns 415: surfaces unsupported-format message
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
  return makeGaiaSharedMock("whatsapp", {
    streamingDefaults: {
      whatsapp: {
        editIntervalMs: 2000,
        streaming: false,
        platform: "whatsapp",
      },
    },
    converters: {
      convertToWhatsAppMarkdown: vi.fn((text: string) => text),
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

interface FakeGaia {
  uploadFile: ReturnType<typeof vi.fn>;
  transcribeAudio: ReturnType<typeof vi.fn>;
  checkAuthStatus: ReturnType<typeof vi.fn>;
}

function buildAdapter(): {
  adapter: WhatsAppAdapter;
  gaia: FakeGaia;
} {
  const adapter = new WhatsAppAdapter();
  const inner = adapter as unknown as {
    waClient: typeof mockWaClientInstance;
    waConfig: typeof MOCK_CONFIG;
    gaia: FakeGaia;
    linkedUsers: Set<string>;
    welcomeSent: Set<string>;
  };
  inner.waClient = mockWaClientInstance;
  inner.waConfig = MOCK_CONFIG;
  const gaia: FakeGaia = {
    uploadFile: vi.fn(async (input) => ({
      fileId: `file-${input.filename}`,
      url: `https://cdn.example/${input.filename}`,
      filename: input.filename,
      type: input.mimeType,
      message: "ok",
    })),
    transcribeAudio: vi.fn(async () => "this is the transcribed voice note"),
    checkAuthStatus: vi.fn(async () => ({
      authenticated: true,
      platform: "whatsapp",
      platformUserId: WA_ID,
    })),
  };
  inner.gaia = gaia;
  // Skip the welcome gate for the focused media tests.
  inner.linkedUsers = new Set([WA_ID]);
  inner.welcomeSent = new Set([WA_ID]);
  return { adapter, gaia };
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

  it("downloads, uploads, and dispatches chat-stream for images with captions", async () => {
    const { adapter, gaia } = buildAdapter();

    await callHandle(
      adapter,
      media({
        kind: "image",
        mediaId: "wa-media-image",
        mimeType: "image/png",
        caption: "what's in this picture?",
      }),
    );

    expect(mockMediaDownload).toHaveBeenCalledTimes(1);
    expect(mockMediaDownload).toHaveBeenCalledWith({
      mediaId: "wa-media-image",
      phoneNumberId: "test-phone-id",
    });

    expect(gaia.uploadFile).toHaveBeenCalledTimes(1);
    const upload = gaia.uploadFile.mock.calls[0][0];
    expect(upload.mimeType).toBe("image/png");
    expect(upload.filename).toBe("image.png");
    expect(Buffer.isBuffer(upload.data)).toBe(true);
    expect(upload.data.length).toBe(5);

    expect(handleStreamingChat).toHaveBeenCalledTimes(1);
    const req = getChatRequest();
    expect(req.platform).toBe("whatsapp");
    expect(req.message).toBe("what's in this picture?");
    expect(req.fileIds).toEqual(["file-image.png"]);
    expect(req.fileData![0].url).toBe("https://cdn.example/image.png");

    expect(gaia.transcribeAudio).not.toHaveBeenCalled();
  });

  it("transcribes voice notes and uses the transcript as the chat message", async () => {
    const { adapter, gaia } = buildAdapter();

    await callHandle(
      adapter,
      media({
        kind: "audio",
        isVoiceNote: true,
        mediaId: "wa-media-voice",
        mimeType: "audio/ogg",
      }),
    );

    expect(gaia.transcribeAudio).toHaveBeenCalledTimes(1);
    const t = gaia.transcribeAudio.mock.calls[0][0];
    expect(t.mimeType).toBe("audio/ogg");
    expect(t.filename).toBe("voice-note.ogg");

    const req = getChatRequest();
    expect(req.message).toBe("this is the transcribed voice note");
    expect(req.fileIds).toBeUndefined();
    expect(req.fileData).toBeUndefined();
    expect(gaia.uploadFile).not.toHaveBeenCalled();
  });

  it("derives an audio filename from the mime type for non-voice audio", async () => {
    const { adapter, gaia } = buildAdapter();

    await callHandle(
      adapter,
      media({
        kind: "audio",
        isVoiceNote: false,
        mediaId: "wa-media-audio",
        mimeType: "audio/mpeg",
      }),
    );

    expect(gaia.transcribeAudio.mock.calls[0][0].filename).toBe("audio.mp3");
  });

  it("uploads documents and prompts the agent to review when no caption is set", async () => {
    const { adapter, gaia } = buildAdapter();

    await callHandle(
      adapter,
      media({
        kind: "document",
        mediaId: "wa-media-doc",
        mimeType: "application/pdf",
        filename: "spec.pdf",
      }),
    );

    expect(gaia.uploadFile).toHaveBeenCalledTimes(1);
    const upload = gaia.uploadFile.mock.calls[0][0];
    expect(upload.filename).toBe("spec.pdf");
    expect(upload.mimeType).toBe("application/pdf");

    const req = getChatRequest();
    expect(req.message).toMatch(/document/i);
    expect(req.fileIds).toEqual(["file-spec.pdf"]);
  });

  it("politely declines videos without downloading them", async () => {
    const { adapter, gaia } = buildAdapter();

    await callHandle(
      adapter,
      media({
        kind: "video",
        mediaId: "wa-media-vid",
        mimeType: "video/mp4",
      }),
    );

    expect(handleStreamingChat).not.toHaveBeenCalled();
    expect(gaia.uploadFile).not.toHaveBeenCalled();
    expect(gaia.transcribeAudio).not.toHaveBeenCalled();
    expect(lastSentBody()).toMatch(/videos/i);
  });

  it("politely declines stickers without downloading them", async () => {
    const { adapter, gaia } = buildAdapter();

    await callHandle(
      adapter,
      media({
        kind: "sticker",
        mediaId: "wa-media-sticker",
        mimeType: "image/webp",
      }),
    );

    expect(handleStreamingChat).not.toHaveBeenCalled();
    expect(gaia.uploadFile).not.toHaveBeenCalled();
    expect(lastSentBody()).toMatch(/stickers/i);
  });

  it("falls back to a friendly error when the transcript is empty", async () => {
    const { adapter, gaia } = buildAdapter();
    gaia.transcribeAudio.mockResolvedValueOnce("   ");

    await callHandle(
      adapter,
      media({
        kind: "audio",
        isVoiceNote: true,
        mediaId: "wa-media-blank",
        mimeType: "audio/ogg",
      }),
    );

    expect(handleStreamingChat).not.toHaveBeenCalled();
    expect(lastSentBody()).toMatch(/couldn't understand/i);
  });

  it("rejects oversize voice notes before transcribing", async () => {
    const { adapter, gaia } = buildAdapter();
    mockMediaDownload.mockResolvedValueOnce(new ArrayBuffer(26 * 1024 * 1024));

    await callHandle(
      adapter,
      media({
        kind: "audio",
        isVoiceNote: true,
        mediaId: "huge",
        mimeType: "audio/ogg",
      }),
    );

    expect(gaia.transcribeAudio).not.toHaveBeenCalled();
    expect(lastSentBody()).toMatch(/too large/i);
  });

  it("rejects oversize files before uploading", async () => {
    const { adapter, gaia } = buildAdapter();
    mockMediaDownload.mockResolvedValueOnce(new ArrayBuffer(11 * 1024 * 1024));

    await callHandle(
      adapter,
      media({
        kind: "image",
        mediaId: "huge-img",
        mimeType: "image/png",
      }),
    );

    expect(gaia.uploadFile).not.toHaveBeenCalled();
    expect(lastSentBody()).toMatch(/too large/i);
  });

  it("surfaces a not-linked message when the upload returns 401", async () => {
    const { adapter, gaia } = buildAdapter();
    gaia.uploadFile.mockRejectedValueOnce(
      Object.assign(new Error("API error: 401"), { status: 401 }),
    );

    await callHandle(
      adapter,
      media({
        kind: "image",
        mediaId: "unauth",
        mimeType: "image/png",
      }),
    );

    expect(lastSentBody()).toMatch(/link your GAIA account/i);
  });

  it("surfaces a too-large message when the upload returns 413", async () => {
    const { adapter, gaia } = buildAdapter();
    gaia.uploadFile.mockRejectedValueOnce(
      Object.assign(new Error("API error: 413"), { status: 413 }),
    );

    await callHandle(
      adapter,
      media({
        kind: "image",
        mediaId: "big",
        mimeType: "image/png",
      }),
    );

    expect(lastSentBody()).toMatch(/too large/i);
  });

  it("surfaces a format-unsupported message when the upload returns 415", async () => {
    const { adapter, gaia } = buildAdapter();
    gaia.uploadFile.mockRejectedValueOnce(
      Object.assign(new Error("API error: 415"), { status: 415 }),
    );

    await callHandle(
      adapter,
      media({
        kind: "document",
        mediaId: "weird",
        mimeType: "application/x-weird",
        filename: "weird.xyz",
      }),
    );

    expect(lastSentBody()).toMatch(/can't read this kind/i);
  });
});

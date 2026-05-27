/**
 * Tests for the shared inbound-media pipeline (libs/shared/ts/src/bots/utils/media.ts).
 *
 * This is where the platform-agnostic media decision lives (transcribe vs
 * upload vs reject, size caps, prompts, error copy), so WhatsApp and Telegram
 * both route through it. The tests import the REAL functions and mock only the
 * GAIA client at the boundary (uploadFile / transcribeAudio), then assert the
 * actual outcome — so they catch any regression in the routing logic itself.
 */
import {
  BOT_MEDIA_LIMITS,
  extensionForMime,
  friendlyMediaError,
  GaiaApiError,
  type IncomingMedia,
  processBotMedia,
  unsupportedMediaMessage,
} from "@gaia/shared";
import { describe, expect, it, vi } from "vitest";

// A fake GaiaClient exposing only the two methods processBotMedia uses. We
// type it through the real parameter type so a signature change breaks here.
function makeGaia(overrides?: {
  transcript?: string;
  uploadThrows?: unknown;
  transcribeThrows?: unknown;
}) {
  const uploadFile = vi.fn(async (input: { filename: string }) => {
    if (overrides?.uploadThrows) throw overrides.uploadThrows;
    return {
      fileId: "file-123",
      url: `https://cdn.gaia/${input.filename}`,
      filename: input.filename,
      type: "file",
    };
  });
  const transcribeAudio = vi.fn(async () => {
    if (overrides?.transcribeThrows) throw overrides.transcribeThrows;
    return overrides?.transcript ?? "the transcribed text";
  });
  return { uploadFile, transcribeAudio };
}

type Gaia = Parameters<typeof processBotMedia>[0];

const ctx = { platform: "telegram" as const, platformUserId: "u1" };
const bytes = (n: number) => async () => new Uint8Array(n);

const media = (over: Partial<IncomingMedia>): IncomingMedia => ({
  kind: "image",
  isVoiceNote: false,
  mimeType: "image/png",
  ...over,
});

describe("processBotMedia — image / document upload path", () => {
  it("uploads an image and returns a chat turn with the attachment", async () => {
    const gaia = makeGaia();
    const outcome = await processBotMedia(
      gaia as unknown as Gaia,
      media({ kind: "image", mimeType: "image/png" }),
      bytes(1000),
      ctx,
    );

    expect(gaia.uploadFile).toHaveBeenCalledOnce();
    expect(gaia.uploadFile.mock.calls[0][0]).toMatchObject({
      filename: "image.png",
      mimeType: "image/png",
    });
    expect(outcome).toEqual({
      action: "chat",
      text: "Please describe this image.",
      attachments: [
        expect.objectContaining({ fileId: "file-123", filename: "image.png" }),
      ],
    });
  });

  it("uses the original filename and a review prompt for a document", async () => {
    const gaia = makeGaia();
    const outcome = await processBotMedia(
      gaia as unknown as Gaia,
      media({
        kind: "document",
        mimeType: "application/pdf",
        filename: "q3.pdf",
      }),
      bytes(1000),
      ctx,
    );

    expect(gaia.uploadFile.mock.calls[0][0]).toMatchObject({
      filename: "q3.pdf",
    });
    expect(outcome).toMatchObject({
      action: "chat",
      text: "Please review this document and tell me what's in it.",
    });
  });

  it("falls back to a 'file' noun for a document with no filename", async () => {
    const outcome = await processBotMedia(
      makeGaia() as unknown as Gaia,
      media({ kind: "document", mimeType: "application/pdf" }),
      bytes(1000),
      ctx,
    );
    expect(outcome).toMatchObject({
      text: "Please review this file and tell me what's in it.",
    });
  });

  it("uses the caption as the prompt when one is present", async () => {
    const outcome = await processBotMedia(
      makeGaia() as unknown as Gaia,
      media({ kind: "image", caption: "  what brand is this?  " }),
      bytes(1000),
      ctx,
    );
    expect(outcome).toMatchObject({ text: "what brand is this?" });
  });

  it("rejects a file over the upload cap WITHOUT uploading", async () => {
    const gaia = makeGaia();
    const outcome = await processBotMedia(
      gaia as unknown as Gaia,
      media({ kind: "image" }),
      bytes(BOT_MEDIA_LIMITS.file + 1),
      ctx,
    );
    expect(gaia.uploadFile).not.toHaveBeenCalled();
    expect(outcome).toEqual({
      action: "reply",
      text: "That file is too large to process (limit: 10 MB). Please share a smaller file.",
    });
  });
});

describe("processBotMedia — audio / voice transcription path", () => {
  it("transcribes a voice note and returns the transcript as the chat turn", async () => {
    const gaia = makeGaia({ transcript: "  hello there  " });
    const outcome = await processBotMedia(
      gaia as unknown as Gaia,
      media({ kind: "audio", isVoiceNote: true, mimeType: "audio/ogg" }),
      bytes(1000),
      ctx,
    );

    expect(gaia.uploadFile).not.toHaveBeenCalled();
    expect(gaia.transcribeAudio.mock.calls[0][0]).toMatchObject({
      filename: "voice-note.ogg",
    });
    expect(outcome).toEqual({
      action: "chat",
      text: "hello there",
      attachments: [],
    });
  });

  it("derives the audio filename from the mime type for non-voice audio", async () => {
    const gaia = makeGaia();
    await processBotMedia(
      gaia as unknown as Gaia,
      media({ kind: "audio", isVoiceNote: false, mimeType: "audio/mpeg" }),
      bytes(1000),
      ctx,
    );
    expect(gaia.transcribeAudio.mock.calls[0][0]).toMatchObject({
      filename: "audio.mp3",
    });
  });

  it("prepends the caption to the transcript when both are present", async () => {
    const outcome = await processBotMedia(
      makeGaia({ transcript: "spoken words" }) as unknown as Gaia,
      media({ kind: "audio", isVoiceNote: true, caption: "context:" }),
      bytes(1000),
      ctx,
    );
    expect(outcome).toMatchObject({ text: "context:\n\nspoken words" });
  });

  it("replies with a retry prompt when the transcript is empty", async () => {
    const outcome = await processBotMedia(
      makeGaia({ transcript: "   " }) as unknown as Gaia,
      media({ kind: "audio", isVoiceNote: true }),
      bytes(1000),
      ctx,
    );
    expect(outcome).toEqual({
      action: "reply",
      text: "I couldn't understand that audio. Could you try recording again or sending a text message?",
    });
  });

  it("rejects audio over the transcribe cap WITHOUT transcribing", async () => {
    const gaia = makeGaia();
    const outcome = await processBotMedia(
      gaia as unknown as Gaia,
      media({ kind: "audio", isVoiceNote: true }),
      bytes(BOT_MEDIA_LIMITS.audio + 1),
      ctx,
    );
    expect(gaia.transcribeAudio).not.toHaveBeenCalled();
    expect(outcome).toMatchObject({
      action: "reply",
      text: "That voice note is too large to transcribe (limit: 25 MB). Please send a shorter message.",
    });
  });
});

describe("processBotMedia — unsupported kinds never download", () => {
  it.each([
    "video",
    "sticker",
  ] as const)("rejects %s without invoking the download thunk", async (kind) => {
    const download = vi.fn(async () => new Uint8Array(10));
    const gaia = makeGaia();
    const outcome = await processBotMedia(
      gaia as unknown as Gaia,
      media({ kind }),
      download,
      ctx,
    );
    expect(download).not.toHaveBeenCalled();
    expect(gaia.uploadFile).not.toHaveBeenCalled();
    expect(outcome).toEqual({
      action: "reply",
      text: unsupportedMediaMessage(kind),
    });
  });
});

describe("processBotMedia — propagates upload/transcribe failures", () => {
  it("lets a GaiaApiError from uploadFile bubble up (adapter maps it)", async () => {
    const err = new GaiaApiError("nope", 413);
    await expect(
      processBotMedia(
        makeGaia({ uploadThrows: err }) as unknown as Gaia,
        media({ kind: "image" }),
        bytes(1000),
        ctx,
      ),
    ).rejects.toBe(err);
  });
});

describe("friendlyMediaError", () => {
  it.each([
    [401, "link your GAIA account"],
    [403, "link your GAIA account"],
    [413, "too large"],
    [415, "can't read this kind"],
    [429, "upload limit"],
  ])("maps HTTP %i to a helpful reply", (status, fragment) => {
    expect(
      friendlyMediaError("image", new GaiaApiError("x", status)),
    ).toContain(fragment);
  });

  it("falls back to a generic message for unknown errors", () => {
    expect(friendlyMediaError("document", new Error("boom"))).toBe(
      "Something went wrong while processing your attachment. Please try again in a moment.",
    );
  });
});

describe("extensionForMime", () => {
  it("maps known mime types to a leading-dot extension", () => {
    expect(extensionForMime("image/jpeg", ".bin")).toBe(".jpg");
    expect(extensionForMime("application/pdf", ".bin")).toBe(".pdf");
    expect(extensionForMime("audio/ogg; codecs=opus", ".bin")).toBe(".ogg");
  });

  it("returns the fallback for unknown mime types", () => {
    expect(extensionForMime("application/x-weird", ".bin")).toBe(".bin");
  });
});

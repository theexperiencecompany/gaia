/**
 * Shared inbound-media pipeline for bot adapters.
 *
 * Every platform receives media differently — WhatsApp via the Kapso webhook +
 * media id, Telegram via `getFile` + `file_id` — but once the raw bytes are in
 * hand the decision is identical:
 *
 *   - video / sticker    → not supported yet, polite reply (no download)
 *   - audio / voice note → transcribe (Whisper) → treat transcript as the message
 *   - image / document   → upload to GAIA storage → attach via fileIds/fileData
 *
 * This module owns that decision plus the size caps, filenames, prompts and
 * error copy that go with it, so every adapter behaves identically and the
 * logic is unit-testable without any platform SDK. Adapters supply only a
 * platform-specific {@link IncomingMedia} descriptor and a download thunk.
 */
import type { GaiaClient } from "../api";
import type { BotFileData, BotUserContext, PlatformName } from "../types";

const MB = 1024 * 1024;

/** Upload/transcribe size caps shared by every platform. */
export const BOT_MEDIA_LIMITS = {
  /** GAIA upload pipeline cap (the backend rejects anything larger). */
  file: 10 * MB,
  /** OpenAI Whisper hard cap, matched by the backend transcribe endpoint. */
  audio: 25 * MB,
} as const;

/**
 * Max bytes a backend-originated artifact may be to deliver on each platform.
 * Conservative per-platform document caps — over these, the bot sends a short
 * "too large" note instead of attempting an upload the platform would reject
 * (which would dead-letter with no user feedback). The artifact download itself
 * is capped at 100 MB (GaiaClient.downloadArtifact) to match the largest cap
 * below, so every per-platform limit here is fully effective.
 */
export const OUTBOUND_FILE_LIMITS: Record<PlatformName, number> = {
  discord: 8 * MB, // non-boosted server upload limit (safe floor)
  slack: 50 * MB,
  telegram: 50 * MB, // bot API sendDocument limit
  whatsapp: 100 * MB, // WhatsApp document limit
};

/** Normalised media kind, identical across platforms. */
export type MediaKind = "image" | "audio" | "video" | "document" | "sticker";

/**
 * Platform-agnostic descriptor of an inbound media message. Each adapter maps
 * its native payload (Kapso `ExtractedMedia`, Telegram `PhotoSize`/`Voice`/…)
 * onto this shape before handing it to {@link processBotMedia}.
 */
export interface IncomingMedia {
  kind: MediaKind;
  /** True for push-to-talk voice notes (only meaningful when `kind === "audio"`). */
  isVoiceNote: boolean;
  /** Best-known mime type; callers fall back to a per-kind default upstream. */
  mimeType: string;
  /** Original filename for documents; absent for inline media. */
  filename?: string;
  /** Caption sent alongside the media, used as the prompt when present. */
  caption?: string;
}

/**
 * Result of {@link processBotMedia}. The adapter either streams a chat turn
 * (optionally with uploaded attachments) or sends a single plain reply.
 */
export type MediaOutcome =
  | { action: "chat"; text: string; attachments: BotFileData[] }
  | { action: "reply"; text: string };

/** Reply shown for media kinds GAIA does not process yet (video, sticker, …). */
export function unsupportedMediaMessage(kind: string): string {
  const labels: Record<string, string> = {
    video: "videos",
    sticker: "stickers",
  };
  const label = labels[kind] ?? `${kind} messages`;
  return `I can't process ${label} yet — please send your message as text, an image, a document, or a voice note. Type /help for available commands.`;
}

/**
 * Maps an upload/transcribe failure to a user-facing reply. Pass `pricingUrl`
 * so the rate-limit (429) reply can point users at the upgrade page, matching
 * the chat-stream rate-limit notice.
 */
export function friendlyMediaError(
  kind: MediaKind,
  err: unknown,
  pricingUrl?: string,
): string {
  const status = (err as { status?: number })?.status;
  const responseStatus = (err as { response?: { status?: number } })?.response
    ?.status;
  const code = status ?? responseStatus;

  if (code === 401 || code === 403) {
    return "I need you to link your GAIA account first before I can read attachments. Send /auth to get started.";
  }
  if (code === 413) {
    return `That ${kind} is too large for me to process. Please share a smaller file.`;
  }
  if (code === 415) {
    return `I can't read this kind of ${kind} yet. Try a common format like JPG, PNG, PDF, or an OGG voice note.`;
  }
  if (code === 429) {
    const what = kind === "audio" ? "voice transcription" : "file upload";
    const base = `You've reached your ${what} limit for now. Please try again later, or upgrade your plan for higher limits.`;
    return pricingUrl ? `${base}\n${pricingUrl}` : base;
  }
  return "Something went wrong while processing your attachment. Please try again in a moment.";
}

/**
 * Maps a MIME type to a {@link MediaKind}. Adapters that learn the kind from a
 * content type (Discord attachments, Slack files) use this; platforms that
 * carry an explicit kind (Telegram, Kapso) set it directly. Never returns
 * "sticker" — stickers are detected from platform-specific fields, not MIME.
 */
export function mediaKindFromMime(mimeType: string): MediaKind {
  const mime = mimeType.split(";")[0].trim().toLowerCase();
  if (mime.startsWith("image/")) return "image";
  if (mime.startsWith("audio/")) return "audio";
  if (mime.startsWith("video/")) return "video";
  return "document";
}

/** Returns a leading-dot file extension for a known mime type, or `fallback`. */
export function extensionForMime(mimeType: string, fallback: string): string {
  const mime = mimeType.split(";")[0].trim().toLowerCase();
  const lookup: Record<string, string> = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "audio/ogg": ".ogg",
    "audio/opus": ".opus",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".m4a",
    "audio/m4a": ".m4a",
    "audio/wav": ".wav",
    "audio/webm": ".webm",
    "audio/aac": ".aac",
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
      ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
      ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation":
      ".pptx",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "text/csv": ".csv",
    "application/json": ".json",
  };
  return lookup[mime] ?? fallback;
}

/**
 * Turns an inbound media message into the next action for the adapter:
 * transcribe audio into a chat turn, upload an image/document and attach it,
 * reject an unsupported kind, or reject an oversize payload.
 *
 * `downloadBytes` is a thunk so unsupported kinds (video, sticker) never incur
 * a download. The only side effects are the GAIA upload/transcribe network
 * calls, injected via {@link GaiaClient}; everything else is pure, which keeps
 * the routing logic testable with a fake client and no platform SDK.
 */
export async function processBotMedia(
  gaia: GaiaClient,
  media: IncomingMedia,
  downloadBytes: () => Promise<Uint8Array>,
  ctx: BotUserContext,
): Promise<MediaOutcome> {
  if (media.kind === "video" || media.kind === "sticker") {
    return { action: "reply", text: unsupportedMediaMessage(media.kind) };
  }

  const bytes = await downloadBytes();

  if (media.kind === "audio") {
    if (bytes.byteLength > BOT_MEDIA_LIMITS.audio) {
      return {
        action: "reply",
        text: `That voice note is too large to transcribe (limit: ${
          BOT_MEDIA_LIMITS.audio / MB
        } MB). Please send a shorter message.`,
      };
    }

    const filename = media.isVoiceNote
      ? "voice-note.ogg"
      : `audio${extensionForMime(media.mimeType, ".ogg")}`;
    const transcript = (
      await gaia.transcribeAudio(
        { data: Buffer.from(bytes), filename, mimeType: media.mimeType },
        ctx,
      )
    ).trim();

    if (!transcript) {
      return {
        action: "reply",
        text: "I couldn't understand that audio. Could you try recording again or sending a text message?",
      };
    }

    // Caption (if any) precedes the transcript so the agent sees both signals.
    const text = media.caption
      ? `${media.caption.trim()}\n\n${transcript}`
      : transcript;
    return { action: "chat", text, attachments: [] };
  }

  // image | document
  if (bytes.byteLength > BOT_MEDIA_LIMITS.file) {
    return {
      action: "reply",
      text: `That file is too large to process (limit: ${
        BOT_MEDIA_LIMITS.file / MB
      } MB). Please share a smaller file.`,
    };
  }

  const filename =
    media.filename ??
    (media.kind === "image"
      ? `image${extensionForMime(media.mimeType, ".jpg")}`
      : `document${extensionForMime(media.mimeType, "")}`);
  const fileData = await gaia.uploadFile(
    { data: Buffer.from(bytes), filename, mimeType: media.mimeType },
    ctx,
  );

  // Caption is the user's prompt when present; otherwise ask the agent to
  // describe (image) or review (document) the attachment.
  const attachmentNoun = media.filename ? "document" : "file";
  const fallbackPrompt =
    media.kind === "image"
      ? "Please describe this image."
      : `Please review this ${attachmentNoun} and tell me what's in it.`;
  const text = media.caption?.trim() || fallbackPrompt;
  return { action: "chat", text, attachments: [fileData] };
}

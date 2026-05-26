import { createHmac, timingSafeEqual } from "node:crypto";
import type {
  ExtractedMedia,
  KapsoMessageEvent,
  WaMediaPayload,
} from "./webhook.types";

/**
 * Verifies a Kapso webhook signature.
 *
 * Kapso signs the raw request body with HMAC-SHA256 using your webhook secret.
 * The signature is provided in the X-Webhook-Signature header as a raw hex string
 * (no prefix).
 */
export function verifyKapsoSignature(
  rawBody: string,
  signatureHeader: string | null,
  secret: string,
): boolean {
  if (!signatureHeader) return false;
  const expected = createHmac("sha256", secret)
    .update(rawBody, "utf8")
    .digest("hex");
  try {
    return timingSafeEqual(Buffer.from(signatureHeader), Buffer.from(expected));
  } catch {
    return false;
  }
}

/**
 * Extracts the WhatsApp phone number (wa_id) from a Kapso message.received event.
 * wa_id is the sender's phone number without the leading '+', e.g. "15551234567".
 * Kapso provides conversation.phone_number with a leading '+'.
 */
export function extractWaId(event: KapsoMessageEvent): string {
  return event.conversation.phone_number.replace(/^\+/, "");
}

/**
 * Extracts the text body from a Kapso text message event.
 * Returns null if the message is not a text message.
 */
export function extractTextBody(event: KapsoMessageEvent): string | null {
  if (event.message.type !== "text") return null;
  return event.message.text?.body ?? null;
}

// ─── Media descriptor extraction ──────────────────────────────────────────
// Normalises the message-type-specific sub-object into a uniform shape the
// adapter can act on. Returns `null` for non-media or unparseable payloads.

const DEFAULT_MIME_BY_KIND: Record<ExtractedMedia["kind"], string> = {
  image: "image/jpeg",
  audio: "audio/ogg",
  video: "video/mp4",
  document: "application/octet-stream",
  sticker: "image/webp",
};

/**
 * Extracts a normalised {@link ExtractedMedia} descriptor from an inbound
 * WhatsApp message. Returns `null` if the message is text-only or the media
 * payload is missing its `id` (we cannot download without it).
 */
export function extractMedia(event: KapsoMessageEvent): ExtractedMedia | null {
  const { type } = event.message;
  // WhatsApp emits voice notes as type "voice" historically but more recent
  // payloads label them type "audio" with `voice: true`. Treat both as audio.
  const normalisedType = type === "voice" ? "audio" : type;

  // For voice-typed messages, the payload may live under either the original
  // `voice` field (legacy) or `audio` (newer). Probe both so we stay tolerant.
  const candidateKeys =
    type === "voice" ? ["voice", "audio"] : [normalisedType];
  let payload: WaMediaPayload | undefined;
  for (const key of candidateKeys) {
    const p = (
      event.message as unknown as Record<string, WaMediaPayload | undefined>
    )[key];
    if (p) {
      payload = p;
      break;
    }
  }

  if (!payload) return null;

  const supportedKinds: ExtractedMedia["kind"][] = [
    "image",
    "audio",
    "video",
    "document",
    "sticker",
  ];
  if (!supportedKinds.includes(normalisedType as ExtractedMedia["kind"])) {
    return null;
  }
  const kind = normalisedType as ExtractedMedia["kind"];

  if (!payload.id) return null;

  const mimeType =
    payload.mime_type ?? payload.mimeType ?? DEFAULT_MIME_BY_KIND[kind];

  const kapso = event.message.kapso;
  const prefetchedUrl =
    kapso?.media_url ??
    kapso?.mediaUrl ??
    kapso?.media_data?.url ??
    kapso?.mediaData?.url ??
    undefined;

  const isVoiceNote =
    kind === "audio" && (type === "voice" || payload.voice === true);

  return {
    kind,
    isVoiceNote,
    mediaId: payload.id,
    mimeType,
    caption: payload.caption,
    filename: payload.filename,
    prefetchedUrl,
  };
}

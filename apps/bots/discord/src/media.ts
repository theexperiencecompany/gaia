/**
 * Discord inbound-media helpers.
 *
 * Maps a Discord message's attachments/sticker onto the shared
 * {@link IncomingMedia} shape and downloads attachment bytes, so the adapter
 * only wires these into the shared `resolveIncomingMedia` pipeline.
 *
 * @module
 */
import {
  fetchBytesCapped,
  type IncomingMedia,
  MEDIA_READ_TIMEOUT_MS,
  mediaKindFromMime,
} from "@gaia/shared/bots";
import { type Message, MessageFlags } from "discord.js";

/** A Discord attachment/sticker normalised for the shared media pipeline. */
export interface DiscordExtractedMedia {
  /** Public CDN URL for the bytes; empty for stickers (never downloaded). */
  url: string;
  media: Omit<IncomingMedia, "caption">;
}

/**
 * Maps every attachment on a Discord message (or its sticker, when it has no
 * attachments) onto the shared {@link IncomingMedia} shape; empty when the
 * message carries no media. Optional chaining keeps it safe against partial
 * test mocks that omit the `attachments` / `stickers` collections.
 */
export function extractDiscordMedia(message: Message): DiscordExtractedMedia[] {
  const isVoiceNote = message.flags?.has(MessageFlags.IsVoiceMessage) ?? false;
  const attachments = [...(message.attachments?.values() ?? [])].map(
    (attachment) => {
      const mimeType = attachment.contentType ?? "application/octet-stream";
      const kind = mediaKindFromMime(mimeType);
      return {
        url: attachment.url,
        media: {
          kind,
          isVoiceNote,
          mimeType,
          filename: kind === "document" ? attachment.name : undefined,
          sizeBytes: attachment.size,
        },
      };
    },
  );
  if (attachments.length > 0) return attachments;
  if ((message.stickers?.size ?? 0) > 0) {
    return [
      {
        url: "",
        media: { kind: "sticker", isVoiceNote: false, mimeType: "image/png" },
      },
    ];
  }
  return [];
}

/**
 * Downloads a Discord attachment from its public CDN URL, reading at most
 * `maxBytes` so an oversize attachment is rejected without ever being buffered
 * whole.
 */
export function downloadDiscordAttachment(
  url: string,
  maxBytes: number,
): Promise<Uint8Array> {
  return fetchBytesCapped(
    url,
    maxBytes,
    "Discord attachment",
    MEDIA_READ_TIMEOUT_MS,
  );
}

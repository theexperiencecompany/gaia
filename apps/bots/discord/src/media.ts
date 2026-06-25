/**
 * Discord inbound-media helpers.
 *
 * Maps a Discord message's attachment/sticker onto the shared
 * {@link IncomingMedia} shape and downloads attachment bytes, so the adapter
 * only wires these into the shared `resolveIncomingMedia` pipeline.
 *
 * @module
 */
import { type IncomingMedia, mediaKindFromMime } from "@gaia/shared";
import { type Message, MessageFlags } from "discord.js";

/** A Discord attachment/sticker normalised for the shared media pipeline. */
export interface DiscordExtractedMedia {
  /** Public CDN URL for the bytes; empty for stickers (never downloaded). */
  url: string;
  media: Omit<IncomingMedia, "caption">;
}

/**
 * Maps a Discord message's first attachment (or sticker) onto the shared
 * {@link IncomingMedia} shape, or null when the message carries no media.
 * Optional chaining keeps it safe against partial test mocks that omit the
 * `attachments` / `stickers` collections.
 */
export function extractDiscordMedia(
  message: Message,
): DiscordExtractedMedia | null {
  const attachment = message.attachments?.first?.();
  if (attachment) {
    const mimeType = attachment.contentType ?? "application/octet-stream";
    const kind = mediaKindFromMime(mimeType);
    return {
      url: attachment.url,
      media: {
        kind,
        isVoiceNote: message.flags?.has(MessageFlags.IsVoiceMessage) ?? false,
        mimeType,
        filename: kind === "document" ? attachment.name : undefined,
      },
    };
  }
  if ((message.stickers?.size ?? 0) > 0) {
    return {
      url: "",
      media: { kind: "sticker", isVoiceNote: false, mimeType: "image/png" },
    };
  }
  return null;
}

/** Downloads a Discord attachment from its public CDN URL. */
export async function downloadDiscordAttachment(
  url: string,
): Promise<Uint8Array> {
  const res = await fetch(url);
  if (!res.ok) {
    throw Object.assign(
      new Error(`Discord attachment download failed (${res.status})`),
      { status: res.status },
    );
  }
  return new Uint8Array(await res.arrayBuffer());
}

/**
 * Slack inbound-file helpers.
 *
 * Maps the files on a Slack message or @mention onto the shared
 * {@link IncomingMedia} shape and downloads their bytes, so the adapter only
 * wires these into the shared `resolveIncomingMedia` pipeline.
 *
 * @module
 */
import {
  fetchBytesCapped,
  type IncomingMedia,
  MEDIA_READ_TIMEOUT_MS,
  mediaKindFromMime,
} from "@gaia/shared/bots";

/** The fields GAIA reads from a Slack file object (message and app_mention events alike). */
export interface SlackInboundFile {
  name: string | null;
  mimetype: string;
  size: number;
  url_private_download?: string;
}

/** Maps one Slack file onto the shared media shape; the caption is the message text. */
export function slackFileMedia(
  file: SlackInboundFile,
  caption: string | undefined,
): IncomingMedia {
  const mimeType = file.mimetype || "application/octet-stream";
  const kind = mediaKindFromMime(mimeType);
  return {
    kind,
    isVoiceNote: false,
    mimeType,
    filename: kind === "document" ? (file.name ?? undefined) : undefined,
    sizeBytes: file.size,
    caption,
  };
}

/**
 * Downloads a Slack file, reading at most `maxBytes`. url_private_download
 * answers only with the bot token (and the files:read scope).
 */
export function downloadSlackFile(
  url: string,
  token: string,
  maxBytes: number,
): Promise<Uint8Array> {
  return fetchBytesCapped(url, maxBytes, "Slack file", MEDIA_READ_TIMEOUT_MS, {
    Authorization: `Bearer ${token}`,
  });
}

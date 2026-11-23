/** Shapes of the shared inbound-media pipeline (processBotMedia, BaseBotAdapter.resolveIncomingMedia). */
import type { BotFileData } from "../types";

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
  sizeBytes?: number;
}

/**
 * Result of {@link processBotMedia}. The adapter either streams a chat turn
 * (optionally with uploaded attachments) or sends a single plain reply.
 */
export type MediaOutcome =
  | { action: "chat"; text: string; attachments: BotFileData[] }
  | { action: "reply"; text: string };

/** One attachment of an inbound message, with the thunk that fetches its bytes. */
export interface IncomingAttachment {
  media: IncomingMedia;
  /** Absent when the platform sent the attachment with no way to fetch it. */
  download?: (maxBytes: number) => Promise<Uint8Array>;
}

/**
 * What one message's attachments came to. The adapter sends `notice` when it
 * is non-empty, then streams a chat turn when `text` or `attachments` is.
 */
export interface MediaBatchOutcome {
  /** Rejections, failures and the skipped-files line as one message; empty when none. */
  notice: string;
  /** Transcripts when any audio was read, else the first file's prompt. */
  text: string;
  attachments: BotFileData[];
}

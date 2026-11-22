import type { EventProperties } from "../../analytics";
import type { GaiaClient } from "../api";
import type { BotFileData, CommandContext, PlatformName } from "../types";
import { hashLogIdentifier } from "../utils/logger";
import {
  BOT_MAX_FILES_PER_MESSAGE,
  friendlyMediaError,
  processBotMedia,
  skippedFilesMessage,
} from "../utils/media";
import type {
  IncomingAttachment,
  IncomingMedia,
  MediaBatchOutcome,
  MediaOutcome,
} from "../utils/media.types";
import { wideLog, withWideEvent } from "../utils/wide-events";

/** What reading a message's attachments needs from the adapter that received it. */
export interface IncomingMediaDeps {
  platform: PlatformName;
  gaia: GaiaClient;
  buildContext: (userId: string, channelId?: string) => CommandContext;
  recordUpload: (
    userId: string,
    properties: EventProperties["bot:file_uploaded"],
  ) => Promise<void>;
}

/**
 * Reads one message's attachments, up to {@link BOT_MAX_FILES_PER_MESSAGE}, through
 * {@link processBotMedia} and folds them into one outcome. A failed attachment adds a line to the
 * notice and the rest still go through; files past the cap add one skipped-files line.
 *
 * Each attachment gets its own media_intake wide event (download, Whisper, upload), which
 * happens before any chat boundary exists.
 */
export async function resolveIncomingMedia(
  deps: IncomingMediaDeps,
  items: IncomingAttachment[],
  userId: string,
  channelId?: string,
): Promise<MediaBatchOutcome> {
  const read = items.slice(0, BOT_MAX_FILES_PER_MESSAGE);
  const skipped = items.length - read.length;
  const replies: string[] = [];
  const transcripts: string[] = [];
  const attachments: BotFileData[] = [];
  let filePrompt = "";

  // Attachments are independent, so they download and upload concurrently;
  // Promise.all keeps the outcomes in message order.
  const outcomes = await Promise.all(
    read.map(({ media, download }) =>
      withWideEvent(
        "media_intake",
        {
          platform: deps.platform,
          component: "base-adapter",
          user_hash: hashLogIdentifier(userId),
          channel_hash: hashLogIdentifier(channelId),
          media_kind: media.kind,
          is_voice_note: media.isVoiceNote,
          files_in_message: items.length,
          files_skipped: skipped,
        },
        () => intakeOne(deps, media, download, userId, channelId),
      ),
    ),
  );
  for (const outcome of outcomes) {
    if (outcome.action === "reply") {
      replies.push(outcome.text);
    } else if (outcome.attachments.length > 0) {
      attachments.push(...outcome.attachments);
      if (!filePrompt) filePrompt = outcome.text;
    } else {
      transcripts.push(outcome.text);
    }
  }

  if (skipped > 0) replies.push(skippedFilesMessage(skipped));
  const text = transcripts.length > 0 ? transcripts.join("\n\n") : filePrompt;
  return { notice: replies.join("\n\n"), text, attachments };
}

/** One attachment inside its media_intake boundary; a failure becomes the reply the user sees. */
async function intakeOne(
  deps: IncomingMediaDeps,
  media: IncomingMedia,
  download: IncomingAttachment["download"],
  userId: string,
  channelId?: string,
): Promise<MediaOutcome> {
  let outcome: MediaOutcome;
  try {
    outcome = await processBotMedia(
      deps.gaia,
      media,
      download,
      deps.buildContext(userId, channelId),
    );
  } catch (err) {
    wideLog.error("media_intake_failed", { media_kind: media.kind }, err);
    return {
      action: "reply",
      text: friendlyMediaError(media.kind, err, deps.gaia.getPricingUrl()),
    };
  }
  // Every inbound attachment on every platform funnels through here, the one place to
  // count uploads. `outcome` separates an ingested attachment ("chat") from a rejected
  // one ("reply") — rejection rate is worth watching. No filename: it's user content.
  await deps.recordUpload(userId, {
    media_kind: media.kind,
    is_voice_note: Boolean(media.isVoiceNote),
    outcome: outcome.action === "chat" ? "ingested" : "rejected",
  });
  return outcome;
}

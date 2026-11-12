/**
 * Renders one conversation's event stream to a chat platform.
 *
 * Frames are folded into the shared conversation view (applyFrame), which makes
 * every frame idempotent: a frame that changes nothing renders nothing, so a
 * replay after a reconnect sends nothing twice. What changed is then rendered:
 *
 * - a reply's deltas stream into edited messages on live platforms (Telegram,
 *   Slack); the others send the reply's saved text once it settles;
 * - a Reply's quote_target, known when it opens, makes its first message a
 *   native reply to that user message's platform message;
 * - a user message's reaction becomes a native reaction on it;
 * - the typing indicator runs while GAIA is thinking or working.
 *
 * Entries at or below the floor (the seq the follow started after) are history:
 * the stream also replays them, and they were delivered by an earlier follow.
 */

import { ENTRY_KIND } from "../../conversation/entries";
import { DISPLAY_STATE, FRAME_KIND } from "../../conversation/frames";
import type {
  ConversationFrame,
  ConversationView,
  Entry,
  LoggedEntry,
  Reply,
} from "../../conversation/types";
import { applyFrame, EMPTY_CONVERSATION_VIEW } from "../../conversation/view";
import { REPLY_FAILURE_LINE } from "../utils/error-lines";
import { PLATFORM_MARKDOWN } from "../utils/formatters";
import { createBotLogger } from "../utils/logger";
import { REACTION_OUTCOME } from "../utils/reaction-outcome";
import type {
  ConversationSurface,
  FollowSummary,
  StreamingOptions,
} from "./follower.types";
import { ReplyDelivery } from "./reply-delivery";

const logger = createBotLogger("shared", "conversation-follower");

type UserMessageEntry = Extract<Entry, { kind: "user_message" }>;
type ReplySettledEntry = Extract<Entry, { kind: "reply_settled" }>;

/** Display states during which the user should see GAIA typing. */
const TYPING_DISPLAYS: ReadonlySet<string> = new Set([
  DISPLAY_STATE.THINKING,
  DISPLAY_STATE.WORKING,
]);

/** The reply streaming now: its delivery, and the attempts that streamed into it. */
interface OpenReply {
  delivery: ReplyDelivery;
  attempts: Set<string>;
}

export class ConversationFollower {
  private view: ConversationView = EMPTY_CONVERSATION_VIEW;
  /** Seqs of the messages this follow must see answered or stopped. */
  private readonly expected = new Set<number>();
  /** The newest seq a settled reply or a stop has covered. */
  private covered = 0;
  private open: OpenReply | null = null;
  /** Reply ids already finished on the platform. */
  private readonly finishedReplies = new Set<string>();
  /** The emoji GAIA has on each user message, by entry id. */
  private readonly placed = new Map<string, string>();
  private stopTyping: (() => void) | null = null;
  private previewTimer: ReturnType<typeof setTimeout> | null = null;
  private lastPreviewAt = 0;
  /** Every platform call, one at a time and in frame order. */
  private chain: Promise<void> = Promise.resolve();
  private closed = false;
  readonly summary: FollowSummary = {
    repliesDelivered: 0,
    reactionsPlaced: 0,
  };

  constructor(
    private readonly floor: number,
    private readonly options: StreamingOptions,
    private readonly surface: ConversationSurface,
  ) {}

  /** A message posted into this conversation: the follow stays until it is answered. */
  expect(seq: number): void {
    this.expected.add(seq);
  }

  /** Idle, and every posted message answered or stopped. */
  get finished(): boolean {
    return (
      this.view.display === DISPLAY_STATE.IDLE &&
      [...this.expected].every((seq) => seq <= this.covered)
    );
  }

  /** Fold one frame in and render what it changed; resolves once the platform calls are done. */
  apply(frame: ConversationFrame): Promise<void> {
    const before = this.view;
    const outcome = applyFrame(before, frame);
    this.view = outcome.view;
    if (outcome.status === "index_gap") {
      // The reply's saved text replaces what streamed when it settles.
      logger.info("reply_delta_gap", { expected: outcome.expected });
    }
    if (outcome.view === before) return this.chain;
    return this.enqueue(() => this.render(frame));
  }

  /** Stop typing and previews; nothing renders after this. */
  close(): void {
    this.closed = true;
    this.clearPreview();
    this.stopTyping?.();
    this.stopTyping = null;
  }

  private enqueue(fn: () => Promise<void>): Promise<void> {
    this.chain = this.chain.then(() => (this.closed ? undefined : fn()));
    return this.chain;
  }

  private async render(frame: ConversationFrame): Promise<void> {
    switch (frame.kind) {
      case FRAME_KIND.ENTRY:
      case FRAME_KIND.ENTRY_UPDATED:
        if (frame.seq > this.floor) await this.renderEntry(frame.seq);
        return;
      case FRAME_KIND.REPLY_DELTA:
        await this.renderDelta(frame.attempt_id, frame.payload);
        return;
      case FRAME_KIND.RETRACT:
        if (this.options.streaming && this.open?.attempts.has(frame.attempt_id))
          await this.open.delivery.boundary(true);
        return;
      case FRAME_KIND.STATE:
        this.renderTyping();
        return;
      case FRAME_KIND.WORK_DELTA:
        // Tool cards and progress are web-only; a bot hears about work in its reply.
        return;
      default: {
        const unhandled: never = frame;
        return unhandled;
      }
    }
  }

  private async renderEntry(seq: number): Promise<void> {
    const logged = this.view.entries.find((held) => held.seq === seq);
    if (!logged) return;
    const { entry } = logged;
    switch (entry.kind) {
      case ENTRY_KIND.USER_MESSAGE:
        await this.renderReaction(entry);
        return;
      case ENTRY_KIND.STOP_REQUESTED:
        this.covered = Math.max(this.covered, seq);
        return;
      case ENTRY_KIND.REPLY_SETTLED:
        this.covered = Math.max(this.covered, entry.through);
        await this.finishReply(entry);
        return;
      default:
        return;
    }
  }

  private async renderReaction(message: UserMessageEntry): Promise<void> {
    const { reaction, platform_message_id: target } = message;
    if (!reaction || !target) return;
    const replaces = this.placed.get(message.id) ?? null;
    if (replaces === reaction.emoji) return;
    this.placed.set(message.id, reaction.emoji);
    const outcome = await this.surface.react(target, reaction.emoji, replaces);
    if (outcome === REACTION_OUTCOME.ATTACHED) {
      this.summary.reactionsPlaced += 1;
      return;
    }
    // A chat model's reaction is its whole answer: one the platform cannot attach is sent as text.
    if (reaction.by === "chat_model") {
      await this.surface.send(reaction.emoji, null);
    }
  }

  /** The open reply for an attempt whose Reply entry is past the floor; null for history. */
  private replyFor(attemptId: string): OpenReply | null {
    if (this.open?.attempts.has(attemptId)) return this.open;
    const opened = this.view.entries.find(
      ({ seq, entry }) =>
        seq > this.floor &&
        entry.kind === ENTRY_KIND.REPLY &&
        entry.attempt_id === attemptId,
    )?.entry;
    if (opened?.kind !== ENTRY_KIND.REPLY) return null;
    // A retracted attempt leaves its reply open: the next attempt overwrites it in place.
    this.open ??= { delivery: this.newDelivery(opened), attempts: new Set() };
    this.open.attempts.add(attemptId);
    return this.open;
  }

  private async renderDelta(
    attemptId: string,
    payload: Extract<ConversationFrame, { kind: "reply_delta" }>["payload"],
  ): Promise<void> {
    if (!this.options.streaming) return;
    const reply = this.replyFor(attemptId);
    if (!reply) return;
    if (payload.type === "response") {
      await reply.delivery.text(payload.chunk);
      this.schedulePreview();
    } else if (payload.type === "message_boundary") {
      await reply.delivery.boundary(payload.discarded);
    }
  }

  private async finishReply(settled: ReplySettledEntry): Promise<void> {
    if (this.finishedReplies.has(settled.reply_id)) return;
    this.finishedReplies.add(settled.reply_id);
    this.clearPreview();
    const reply = this.savedReply(settled.reply_id);
    const delivery = this.open?.delivery ?? this.newDelivery(reply);
    this.open = null;
    const saved = reply?.text ?? "";
    if (delivery.streamed !== saved) {
      // What streamed is not what was saved (a delta gap, or nothing streamed): show the saved text.
      if (delivery.opened) await delivery.boundary(true);
      await delivery.text(saved);
    }
    await delivery.end();
    if (delivery.opened) this.summary.repliesDelivered += 1;
    if (settled.failure) {
      const { platform } = this.options;
      await this.surface.send(
        PLATFORM_MARKDOWN[platform](REPLY_FAILURE_LINE[settled.failure]),
        null,
      );
    }
  }

  private savedReply(replyId: string): Reply | null {
    const reply = this.view.entries.findLast(
      ({ entry }) =>
        entry.kind === ENTRY_KIND.REPLY && entry.reply_id === replyId,
    )?.entry;
    return reply?.kind === ENTRY_KIND.REPLY ? reply : null;
  }

  /** The platform message of the user message a reply quotes, when this follow holds it. */
  private quoteTarget(messageId: string | null): string | null {
    if (!messageId) return null;
    const found: LoggedEntry | undefined = this.view.entries.find(
      ({ entry }) => entry.id === messageId,
    );
    if (found?.entry.kind !== ENTRY_KIND.USER_MESSAGE) {
      logger.info("reply_quote_unknown", { message_id: messageId });
      return null;
    }
    return found.entry.platform_message_id;
  }

  private newDelivery(reply: Reply | null): ReplyDelivery {
    const { platform, streaming } = this.options;
    return new ReplyDelivery(
      { live: streaming, platform, render: PLATFORM_MARKDOWN[platform] },
      this.surface,
      this.quoteTarget(reply?.quote_target ?? null),
    );
  }

  private renderTyping(): void {
    const typing = TYPING_DISPLAYS.has(this.view.display);
    if (typing && !this.stopTyping) {
      this.stopTyping = this.surface.startTyping();
    } else if (!typing && this.stopTyping) {
      this.stopTyping();
      this.stopTyping = null;
    }
  }

  /** Throttle live previews to the platform's edit rate; a sealed bubble needs none. */
  private schedulePreview(): void {
    const sinceLast = Date.now() - this.lastPreviewAt;
    if (sinceLast >= this.options.editIntervalMs) {
      this.clearPreview();
      void this.preview();
    } else if (!this.previewTimer) {
      this.previewTimer = setTimeout(() => {
        this.previewTimer = null;
        void this.preview();
      }, this.options.editIntervalMs - sinceLast);
    }
  }

  private preview(): Promise<void> {
    this.lastPreviewAt = Date.now();
    return this.enqueue(async () => {
      await this.open?.delivery.tick();
    });
  }

  private clearPreview(): void {
    if (this.previewTimer) {
      clearTimeout(this.previewTimer);
      this.previewTimer = null;
    }
  }
}

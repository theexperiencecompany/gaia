/**
 * Renders one conversation's event stream to a chat platform.
 *
 * Frames are folded into the shared copy of the server's screen (applyFrame), which
 * makes every frame idempotent: a frame that changes nothing renders nothing, so
 * the screen a reconnect opens on sends nothing twice. Each screen item maps to
 * platform messages:
 *
 * - a reply item streams its deltas into edited messages on live platforms
 *   (Telegram, Slack); the others send its text once it settles. Its quote makes
 *   its first message a native reply to that user message's platform message;
 * - a user item's reaction becomes a native reaction on it;
 * - a work item's open approvals are asked in chat, every one still open numbered;
 * - the typing indicator runs while GAIA is thinking or working.
 *
 * Items at or below the floor (the seq the follow started after) in the screen the
 * follow opens on are history, delivered by an earlier follow.
 */

import { SCREEN_ITEM_KIND } from "../../conversation/entries";
import { DISPLAY_STATE, FRAME_KIND } from "../../conversation/frames";
import type {
  ConversationFrame,
  ConversationView,
  ScreenItem,
} from "../../conversation/types";
import { applyFrame, EMPTY_CONVERSATION_VIEW } from "../../conversation/view";
import { REPLY_FAILURE_LINE } from "../utils/error-lines";
import { PLATFORM_MARKDOWN } from "../utils/formatters";
import { createBotLogger } from "../utils/logger";
import { REACTION_OUTCOME } from "../utils/reaction-outcome";
import { chunkResponse } from "../utils/text";
import { formatApprovalPrompt } from "./approval-prompt";
import type {
  FollowSummary,
  FollowSurface,
  StreamingOptions,
} from "./follower.types";
import { ReplyDelivery } from "./reply-delivery";

const logger = createBotLogger("shared", "conversation-follower");

type UserItem = Extract<ScreenItem, { kind: "user" }>;
type ReplyItem = Extract<ScreenItem, { kind: "reply" }>;
type NoticeItem = Extract<ScreenItem, { kind: "notice" }>;

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

const sameBubbles = (a: readonly string[], b: readonly string[]): boolean =>
  a.length === b.length && a.every((bubble, at) => bubble === b[at]);

export class ConversationFollower {
  private view: ConversationView = EMPTY_CONVERSATION_VIEW;
  /** Seqs of the messages this follow must see answered or stopped. */
  private readonly expected = new Set<number>();
  /** Whether the screen the follow opens on has arrived. */
  private opened = false;
  /** Approvals already asked on the platform. */
  private readonly asked = new Set<string>();
  /** Notices already sent on the platform. */
  private readonly noticed = new Set<string>();
  /** Whether a state frame arrived: until one does, idle is only the empty view's default. */
  private stated = false;
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
    noticesDelivered: 0,
    filesDelivered: 0,
  };

  constructor(
    private readonly floor: number,
    private readonly options: StreamingOptions,
    private readonly surface: FollowSurface,
    private readonly conversationId: string,
  ) {}

  /** A message posted into this conversation: the follow stays until it is answered. */
  expect(seq: number): void {
    this.expected.add(seq);
  }

  /** Idle, and every posted message answered or stopped. */
  get finished(): boolean {
    return (
      this.stated &&
      this.view.display === DISPLAY_STATE.IDLE &&
      [...this.expected].every((seq) => seq <= this.view.head)
    );
  }

  /** Fold one frame in and render what it changed; resolves once the platform calls are done. */
  apply(frame: ConversationFrame): Promise<void> {
    const before = this.view;
    if (frame.kind === FRAME_KIND.STATE) this.stated = true;
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
      case FRAME_KIND.SCREEN:
        await this.renderItems(this.opening(frame.items));
        return;
      case FRAME_KIND.SCREEN_INSERT:
      case FRAME_KIND.SCREEN_UPDATE:
        await this.renderItems([frame.item]);
        return;
      case FRAME_KIND.REPLY_DELTA:
        await this.renderDelta(frame.attempt_id, frame.reply_id, frame.payload);
        return;
      case FRAME_KIND.RETRACT:
        if (this.options.streaming && this.open?.attempts.has(frame.attempt_id))
          await this.open.delivery.retract();
        return;
      case FRAME_KIND.STATE:
        this.renderTyping();
        return;
      case FRAME_KIND.CONVERSATION_UPDATED:
        // A chat platform shows no conversation title.
        return;
      default: {
        const unhandled: never = frame;
        return unhandled;
      }
    }
  }

  /** Take the first screen's history as delivered; return the items left to render. */
  private opening(items: readonly ScreenItem[]): readonly ScreenItem[] {
    if (this.opened) return items;
    this.opened = true;
    for (const item of items) {
      // Work started before the floor may ask an approval logged after it.
      if (item.kind === SCREEN_ITEM_KIND.WORK && item.asked_seq <= this.floor)
        for (const request of item.asking) this.asked.add(request.approval_id);
      if (item.seq > this.floor) continue;
      if (item.kind === SCREEN_ITEM_KIND.USER && item.message.reaction)
        this.placed.set(item.id, item.message.reaction.emoji);
      if (item.kind === SCREEN_ITEM_KIND.REPLY && item.outcome !== null)
        this.finishedReplies.add(item.id);
      if (item.kind === SCREEN_ITEM_KIND.NOTICE) this.noticed.add(item.id);
    }
    return items.filter((item) => item.seq > this.floor);
  }

  private async renderItems(items: readonly ScreenItem[]): Promise<void> {
    for (const item of items) {
      switch (item.kind) {
        case SCREEN_ITEM_KIND.USER:
          if (item.seq > this.floor) await this.renderReaction(item);
          break;
        case SCREEN_ITEM_KIND.REPLY:
          if (item.outcome !== null) await this.finishReply(item);
          break;
        case SCREEN_ITEM_KIND.WORK:
          if (
            item.asking.some(({ approval_id }) => !this.asked.has(approval_id))
          )
            await this.askApproval();
          break;
        case SCREEN_ITEM_KIND.NOTICE:
          await this.sendNotice(item);
          break;
        // A fired workflow or woken todo shows nothing on a chat platform of its own.
        case SCREEN_ITEM_KIND.WORKFLOW_FIRED:
        case SCREEN_ITEM_KIND.TODO_WOKE:
          break;
        default: {
          const unhandled: never = item;
          return unhandled;
        }
      }
    }
  }

  private async renderReaction({ id, message }: UserItem): Promise<void> {
    const { reaction, platform_message_id: target } = message;
    if (!reaction || !target) return;
    const replaces = this.placed.get(id) ?? null;
    if (replaces === reaction.emoji) return;
    this.placed.set(id, reaction.emoji);
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

  private async sendNotice(notice: NoticeItem): Promise<void> {
    if (this.noticed.has(notice.id)) return;
    this.noticed.add(notice.id);
    const { platform } = this.options;
    const bubbles = notice.bubbles.flatMap((bubble) =>
      chunkResponse(bubble, platform, PLATFORM_MARKDOWN[platform]),
    );
    if (bubbles.length === 0) return;
    await this.surface.sendNotice(bubbles);
    this.summary.noticesDelivered += 1;
  }

  /** Ask about every approval the work waits on, numbered oldest first. */
  private async askApproval(): Promise<void> {
    const open = this.view.items.flatMap((item) =>
      item.kind === SCREEN_ITEM_KIND.WORK ? item.asking : [],
    );
    for (const request of open) this.asked.add(request.approval_id);
    const { platform } = this.options;
    await this.surface.send(
      PLATFORM_MARKDOWN[platform](formatApprovalPrompt(open, Date.now())),
      null,
    );
  }

  /** The open reply an attempt streams into, once its item is past the floor; null for history. */
  private replyFor(
    attemptId: string,
    replyId: string | null,
  ): OpenReply | null {
    if (this.open?.attempts.has(attemptId)) return this.open;
    const opened = this.view.items.find(
      (item): item is ReplyItem =>
        item.kind === SCREEN_ITEM_KIND.REPLY &&
        item.id === replyId &&
        item.seq > this.floor,
    );
    if (!opened) return null;
    // A retracted attempt leaves its reply open: the next attempt overwrites it in place.
    this.open ??= { delivery: this.newDelivery(opened), attempts: new Set() };
    this.open.attempts.add(attemptId);
    return this.open;
  }

  private async renderDelta(
    attemptId: string,
    replyId: string | null,
    payload: Extract<ConversationFrame, { kind: "reply_delta" }>["payload"],
  ): Promise<void> {
    if (!this.options.streaming) return;
    const reply = this.replyFor(attemptId, replyId);
    if (!reply) return;
    if (payload.type !== "bubble_text" && payload.type !== "bubbles") return;
    const draft = this.view.drafts.find((held) => held.attemptId === attemptId);
    if (!draft) return;
    await reply.delivery.bubbles(draft.content.bubbles);
    this.schedulePreview();
  }

  private async finishReply(reply: ReplyItem): Promise<void> {
    if (this.finishedReplies.has(reply.id)) return;
    this.finishedReplies.add(reply.id);
    this.clearPreview();
    const delivery = this.open?.delivery ?? this.newDelivery(reply);
    this.open = null;
    if (!sameBubbles(delivery.streamed, reply.bubbles)) {
      // What streamed is not what was saved (a delta gap, or nothing streamed): show the saved bubbles.
      if (delivery.opened) await delivery.retract();
      await delivery.bubbles(reply.bubbles);
    }
    await delivery.end();
    if (delivery.opened) this.summary.repliesDelivered += 1;
    for (const file of reply.files) {
      await this.surface.sendFile({
        conversationId: this.conversationId,
        path: file.path,
        contentType: file.content_type,
      });
      this.summary.filesDelivered += 1;
    }
    if (reply.failure) {
      const { platform } = this.options;
      await this.surface.send(
        PLATFORM_MARKDOWN[platform](REPLY_FAILURE_LINE[reply.failure]),
        null,
      );
    }
  }

  /** The platform message of the user message a reply quotes, when this follow holds it. */
  private quoteTarget(messageId: string | null): string | null {
    if (!messageId) return null;
    const found = this.view.items.find((item) => item.id === messageId);
    if (found?.kind !== SCREEN_ITEM_KIND.USER) {
      logger.info("reply_quote_unknown", { message_id: messageId });
      return null;
    }
    return found.message.platform_message_id;
  }

  private newDelivery(reply: ReplyItem): ReplyDelivery {
    const { platform, streaming } = this.options;
    return new ReplyDelivery(
      { live: streaming, platform, render: PLATFORM_MARKDOWN[platform] },
      this.surface,
      this.quoteTarget(reply.quote?.id ?? null),
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

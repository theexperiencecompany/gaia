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
 * - a user item's reaction becomes a native reaction on it, or text where the platform refuses it;
 * - a work item's open approvals are asked in chat once each, numbered among every open one,
 *   and its browser run's cards are shown to the requester as they arrive (browser-progress.ts);
 * - a usage limit the run hit is one line with the upgrade link (rate-limit-notice.ts);
 * - notices, and replies the platform's message window has closed on, go through sendNotice;
 * - the typing indicator runs while GAIA is thinking or working.
 *
 * The follow opens after its floor (the seq an earlier follow delivered through), so
 * the server sends only what is new or changed since. An item at or below the floor
 * is history the first time it is seen, whenever that is: what it shows then was
 * delivered by an earlier follow, and only what it gains later is rendered (for work
 * that was not running at that head the server names the cards it showed then, so the
 * cards a re-run published while the bot was away are rendered too). A reply
 * that follow sent only its first bubbles of sends the rest. A reaction amends its message
 * at no seq of its own, so the server owes it apart from the floor until a follow reports
 * it placed. After each platform step the follower records how far it delivered, so a
 * restart resumes exactly there.
 */

import type {
  ApprovalRequested,
  MessageReaction,
  NoticeItem,
  PartialReply,
  ReplyFile,
  ReplyItem,
  ToolTimeline,
  UserItem,
} from "../../api/generated";
import { SCREEN_ITEM_KIND } from "../../conversation/entries";
import { DISPLAY_STATE, FRAME_KIND } from "../../conversation/frames";
import type {
  ConversationFrame,
  ConversationView,
  ScreenItem,
} from "../../conversation/types";
import { applyFrame, EMPTY_CONVERSATION_VIEW } from "../../conversation/view";
import { isChatGone } from "../utils/failure-reasons";
import { PLATFORM_MARKDOWN } from "../utils/formatters";
import { createBotLogger, sanitizeErrorForLog } from "../utils/logger";
import { REACTION_OUTCOME } from "../utils/reaction-outcome";
import { chunkResponse } from "../utils/text";
import { formatApprovalPrompt } from "./approval-prompt";
import {
  BROWSER_CARD_TOOL,
  BrowserProgress,
  browserCards,
} from "./browser-progress";
import type {
  DeliveryCursor,
  DeliveryReport,
  FollowStart,
  FollowSummary,
  FollowSurface,
  PrivateSurface,
  StreamingOptions,
} from "./follower.types";
import { OwedReactions } from "./owed-reactions";
import { RATE_LIMIT_TOOL, rateLimitNotices } from "./rate-limit-notice";
import { ReplyDelivery } from "./reply-delivery";

const logger = createBotLogger("shared", "conversation-follower");

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

const samePartial = (a: PartialReply | null, b: PartialReply | null): boolean =>
  a?.reply_id === b?.reply_id &&
  a?.bubbles === b?.bubbles &&
  sameBubbles(a?.open_message_ids ?? [], b?.open_message_ids ?? []);

/** The log position at which an item has something for the platform: a work item's newest approval. */
const deliverySeq = (item: ScreenItem): number =>
  item.kind === SCREEN_ITEM_KIND.WORK
    ? Math.max(item.seq, item.asked_seq)
    : item.seq;

/** A change had no place in the screen the follower holds: its connection is reopened on the whole screen. */
export class StaleScreen extends Error {
  constructor() {
    super("a change had no place in the screen held");
    this.name = "StaleScreen";
  }
}

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
  /** Reply ids already finished on the platform, or being finished now. */
  private readonly finishedReplies = new Set<string>();
  /** Reply ids this follow finished sending: their bubbles, files and failure line are out. */
  private readonly deliveredReplies = new Set<string>();
  /** The emoji GAIA has on each user message, by entry id. */
  private readonly placed = new Map<string, string>();
  private readonly owedReactions: OwedReactions;
  /** Work items whose usage limit was told: a limit ends the work, so it is told once. */
  private readonly limitTold = new Set<string>();
  /** Each work item's browser run, by item id. */
  private readonly browserRuns = new Map<string, BrowserProgress>();
  /** Items at or below the floor already taken as history. */
  private readonly history = new Set<string>();
  private stopTyping: (() => void) | null = null;
  private previewTimer: ReturnType<typeof setTimeout> | null = null;
  private lastPreviewAt = 0;
  /** Every platform call, one at a time and in frame order. */
  private chain: Promise<void> = Promise.resolve();
  private closed = false;
  private failed: { error: unknown } | null = null;
  /** Whether a change had no place in the screen held: the next connection opens on the whole screen. */
  private stale = false;
  readonly summary: FollowSummary = {
    repliesDelivered: 0,
    reactionsPlaced: 0,
    noticesDelivered: 0,
    filesDelivered: 0,
  };

  private readonly floor: number;
  /** The cursor last recorded. */
  private recorded: Omit<DeliveryCursor, "owed_reactions">;
  /** The reply past the cursor, as far as its bubbles are final on the platform. */
  private progress: PartialReply | null;

  constructor(
    private readonly start: FollowStart,
    private readonly options: StreamingOptions,
    private readonly surface: FollowSurface,
    private readonly conversationId: string,
  ) {
    this.floor = start.floor;
    this.progress = start.partialReply;
    this.recorded = {
      delivered_seq: start.floor,
      partial_reply: start.partialReply,
    };
    this.owedReactions = new OwedReactions(start.owedReactions);
    for (const { message_id, emoji } of start.placedReactions)
      this.placed.set(message_id, emoji);
  }

  /** The emoji this follow has on each user message, for the next follow here. */
  get placedReactions(): MessageReaction[] {
    return [...this.placed].map(([message_id, emoji]) => ({
      message_id,
      emoji,
    }));
  }

  /** How far this follow has put the conversation on the platform. */
  get delivered(): DeliveryCursor {
    return {
      ...this.recorded,
      owed_reactions: this.owedReactions.all,
    };
  }

  /**
   * The log head a connection opens after: the floor until a screen arrived, then the
   * head that screen reached. Null asks for the whole screen, once a change had no place.
   */
  get resumeAfter(): number | null {
    if (this.stale) return null;
    const head = this.opened ? this.view.screenHead : this.floor;
    return head > 0 ? head : null;
  }

  /** A message posted into this conversation: the follow stays until it is answered. */
  expect(seq: number): void {
    this.expected.add(seq);
  }

  /** The approvals the server says the conversation waits on: none unless its state is awaiting approval. */
  get awaitingDecision(): ApprovalRequested[] {
    if (this.view.display !== DISPLAY_STATE.AWAITING_APPROVAL) return [];
    return this.view.items.flatMap((item) =>
      item.kind === SCREEN_ITEM_KIND.WORK ? item.asking : [],
    );
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
    // The whole screen heals whatever the held one lacked.
    if (frame.kind === FRAME_KIND.SCREEN) this.stale = false;
    const outcome = applyFrame(before, frame);
    this.view = outcome.view;
    if (outcome.status === "index_gap") {
      // The reply's saved text replaces what streamed when it settles.
      logger.info("reply_delta_gap", { expected: outcome.expected });
    }
    if (outcome.status === "stale_copy") {
      this.stale = true;
      return Promise.reject(new StaleScreen());
    }
    if (outcome.view !== before) this.enqueue(() => this.render(frame));
    return this.rendered();
  }

  /** A platform call failed (a chat that is gone, a blocked bot): this follow renders nothing more. */
  get deliveryFailed(): boolean {
    return this.failed !== null;
  }

  /** Stop typing and previews; nothing renders after this. */
  close(): void {
    this.closed = true;
    this.clearPreview();
    this.stopTyping?.();
    this.stopTyping = null;
  }

  /**
   * Run fn after every platform call queued before it. The chain itself never rejects,
   * so a voided preview cannot become an unhandled rejection: the first failure closes
   * the follow and is rethrown to whoever awaits a frame.
   */
  private enqueue(fn: () => Promise<void>): Promise<void> {
    this.chain = this.chain.then(async () => {
      if (this.closed) return;
      try {
        await fn();
      } catch (error) {
        this.failed = { error };
        this.close();
      }
    });
    return this.chain;
  }

  private async rendered(): Promise<void> {
    await this.chain;
    if (this.failed) throw this.failed.error;
  }

  private async render(frame: ConversationFrame): Promise<void> {
    await this.renderFrame(frame);
    await this.recordDelivered();
  }

  private async renderFrame(frame: ConversationFrame): Promise<void> {
    switch (frame.kind) {
      case FRAME_KIND.SCREEN:
        this.opened = true;
        await this.renderItems(this.pastHistory(frame.items, frame.held_cards));
        return;
      case FRAME_KIND.SCREEN_INSERT:
      case FRAME_KIND.SCREEN_UPDATE:
        await this.renderItems(this.pastHistory([frame.item]));
        return;
      case FRAME_KIND.SCREEN_PATCH:
        await this.renderItems(
          this.view.items.filter((item) => item.id === frame.id),
        );
        return;
      case FRAME_KIND.REPLY_DELTA:
        await this.renderDelta(frame.attempt_id, frame.reply_id, frame.payload);
        return;
      case FRAME_KIND.RETRACT:
        // Only an attempt that showed no text is withdrawn: nothing it streamed was posted.
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

  /**
   * Take as delivered what each item at or below the floor shows the first time it is
   * seen; return the items left to render: the rest, and work asking past the floor.
   */
  private pastHistory(
    items: readonly ScreenItem[],
    heldCards: Readonly<Record<string, Record<string, number>>> = {},
  ): readonly ScreenItem[] {
    return items.filter((item) => {
      if (item.seq > this.floor || this.history.has(item.id)) return true;
      this.history.add(item.id);
      if (item.kind === SCREEN_ITEM_KIND.WORK)
        return this.workPastHistory(item, heldCards[item.id]);
      // A reaction still owed was never placed, however old its message.
      if (
        item.kind === SCREEN_ITEM_KIND.USER &&
        this.owedReactions.has(item.id)
      )
        return true;
      if (item.kind === SCREEN_ITEM_KIND.USER && item.message.reaction)
        this.placed.set(item.id, item.message.reaction.emoji);
      if (item.kind === SCREEN_ITEM_KIND.REPLY && item.outcome !== null)
        this.finishedReplies.add(item.id);
      if (item.kind === SCREEN_ITEM_KIND.NOTICE) this.noticed.add(item.id);
      return false;
    });
  }

  /**
   * Take as delivered what work at or below the floor showed, and return whether it has more to
   * render. held is how many entries of each card the server says finished work showed at the
   * head this follow opened after, so what it gained since is rendered; without it, everything
   * it shows now is history.
   */
  private workPastHistory(
    item: Extract<ScreenItem, { kind: "work" }>,
    held: Readonly<Record<string, number>> | undefined,
  ): boolean {
    // Work started before the floor may ask an approval logged after it.
    if (item.asked_seq <= this.floor)
      for (const request of item.asking) this.asked.add(request.approval_id);
    const { links } = this.surface;
    const steps = held
      ? (held[BROWSER_CARD_TOOL] ?? 0)
      : browserCards(item.timeline).length;
    const limits = held
      ? (held[RATE_LIMIT_TOOL] ?? 0)
      : rateLimitNotices(item.timeline, links).length;
    this.browserRun(item.id).skip(steps);
    // Work that never hit a limit may still hit one when it runs again.
    if (limits > 0) this.limitTold.add(item.id);
    return held !== undefined || item.asked_seq > this.floor;
  }

  private async renderItems(items: readonly ScreenItem[]): Promise<void> {
    for (const item of items) {
      switch (item.kind) {
        case SCREEN_ITEM_KIND.USER:
          // react-doctor-disable-next-line async-await-in-loop -- screen items render to the platform in log order
          await this.renderReaction(item);
          break;
        case SCREEN_ITEM_KIND.REPLY:
          if (item.outcome !== null) await this.finishReply(item);
          break;
        case SCREEN_ITEM_KIND.WORK:
          if (
            item.asking.some(({ approval_id }) => !this.asked.has(approval_id))
          )
            await this.askApproval();
          await this.browserRun(item.id).render(browserCards(item.timeline));
          await this.tellLimit(item.id, item.timeline);
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

  /**
   * Put a user message's reaction on the platform once, then settle it as placed: one the platform
   * refuses for good is settled too, like a refused file, so it never holds the follow.
   */
  private async renderReaction({ id, message }: UserItem): Promise<void> {
    const { reaction, platform_message_id: target } = message;
    if (!reaction) return;
    const replaces = this.placed.get(id) ?? null;
    if (replaces !== reaction.emoji) {
      this.owedReactions.owe({ message_id: id, emoji: reaction.emoji });
      this.placed.set(id, reaction.emoji);
      // A message with no platform id (one typed on the web) has nowhere to take it.
      if (target) await this.placeReaction(target, reaction, replaces);
    }
    this.owedReactions.settle(id);
  }

  private async placeReaction(
    target: string,
    reaction: NonNullable<UserItem["message"]["reaction"]>,
    replaces: string | null,
  ): Promise<void> {
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
    const { image_url: imageUrl, bubbles } = notice;
    const photoSent = imageUrl
      ? await this.sendNoticePhoto(imageUrl, bubbles[0] ?? "")
      : false;
    const lines = photoSent ? bubbles.slice(1) : bubbles;
    const textSent = await this.sendLines(
      imageUrl && !photoSent ? [...lines, imageUrl] : lines,
    );
    if (photoSent || textSent) this.summary.noticesDelivered += 1;
  }

  /** Send a notice's image captioned with its first bubble; false when the platform would not take it, so the text and link go instead. */
  private async sendNoticePhoto(
    url: string,
    caption: string,
  ): Promise<boolean> {
    try {
      await this.surface.sendPhoto(url, caption);
      return true;
    } catch (error) {
      logger.warn("notice_photo_failed", sanitizeErrorForLog(error));
      return false;
    }
  }

  /** Send lines outside a reply, chunked and rendered for the platform; false when there was nothing to send. */
  private async sendLines(
    lines: readonly string[],
    to: Pick<PrivateSurface, "sendNotice"> = this.surface,
  ): Promise<boolean> {
    const render = PLATFORM_MARKDOWN[this.options.platform];
    const bubbles = lines.flatMap((line) =>
      chunkResponse(line, this.options.platform, render).map(render),
    );
    if (bubbles.length === 0) return false;
    await to.sendNotice(bubbles);
    return true;
  }

  /** Tell the usage limit a work item's run hit, once per item. */
  private async tellLimit(
    itemId: string,
    timeline: ToolTimeline,
  ): Promise<void> {
    if (this.limitTold.has(itemId)) return;
    const lines = rateLimitNotices(timeline, this.surface.links);
    if (lines.length === 0) return;
    this.limitTold.add(itemId);
    await this.sendLines(lines);
  }

  private browserRun(itemId: string): BrowserProgress {
    let run = this.browserRuns.get(itemId);
    if (!run) {
      const { requester } = this.surface;
      run = new BrowserProgress(requester, async (lines) => {
        await this.sendLines(lines, requester);
      });
      this.browserRuns.set(itemId, run);
    }
    return run;
  }

  /** Ask about each approval the work waits on that is not asked yet, numbered among every open one. */
  private async askApproval(): Promise<void> {
    const open = this.view.items.flatMap((item) =>
      item.kind === SCREEN_ITEM_KIND.WORK ? item.asking : [],
    );
    const fresh = open.filter(
      ({ approval_id }) => !this.asked.has(approval_id),
    );
    for (const request of fresh) this.asked.add(request.approval_id);
    const { platform } = this.options;
    await this.surface.send(
      PLATFORM_MARKDOWN[platform](formatApprovalPrompt(open, fresh)),
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
      (item): item is Extract<ScreenItem, { kind: "reply" }> =>
        item.kind === SCREEN_ITEM_KIND.REPLY &&
        item.id === replyId &&
        item.seq > this.floor,
    );
    if (!opened) return null;
    // A retried attempt keeps its reply open: the next attempt's text follows what was shown.
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
    if (payload.type !== "bubble_text") return;
    const draft = this.view.drafts.find((held) => held.attemptId === attemptId);
    if (!draft) return;
    await reply.delivery.bubbles(draft.content.bubbles);
    this.schedulePreview();
  }

  private async finishReply(reply: ReplyItem): Promise<void> {
    if (this.finishedReplies.has(reply.id)) return;
    this.finishedReplies.add(reply.id);
    this.clearPreview();
    const tail = [
      ...rateLimitNotices(reply.timeline, this.surface.links),
      ...(reply.failure_line ? [reply.failure_line] : []),
    ];
    const says = reply.bubbles.length > 0 || tail.length > 0;
    if (says && !this.open && (await this.surface.windowClosed())) {
      // Outside the platform's window only the approved template reaches the user.
      if (await this.sendLines([...reply.bubbles, ...tail]))
        this.summary.repliesDelivered += 1;
    } else {
      await this.streamReply(reply);
      await this.sendLines(tail);
    }
    for (const file of reply.files) {
      // react-doctor-disable-next-line async-await-in-loop -- files follow the reply in the order it attached them
      await this.sendFile(file);
    }
    this.deliveredReplies.add(reply.id);
    this.progress = null;
  }

  /** Put a settled reply's bubbles on the platform, after whatever of it already streamed. */
  private async streamReply(reply: ReplyItem): Promise<void> {
    const delivery = this.open?.delivery ?? this.newDelivery(reply);
    this.open = null;
    if (!sameBubbles(delivery.streamed, reply.bubbles)) {
      // A delta gap, or nothing streamed: the saved bubbles extend whatever was shown.
      await delivery.bubbles(reply.bubbles);
    }
    await delivery.end();
    if (delivery.opened) this.summary.repliesDelivered += 1;
  }

  /** Upload a reply's file; one the platform will not take is named with where to open it. */
  private async sendFile(file: ReplyFile): Promise<void> {
    try {
      await this.surface.sendFile(this.conversationId, file);
      this.summary.filesDelivered += 1;
    } catch (error) {
      if (isChatGone(error)) throw error;
      logger.warn("reply_file_failed", sanitizeErrorForLog(error));
      const name = file.path.split("/").pop() ?? file.path;
      await this.sendLines([
        `I couldn't send ${name} here. Open it in GAIA: ${file.opens_at}`,
      ]);
    }
  }

  /** The platform message of the newest user message on screen, which a coming reply answers. */
  private latestUserMessage(): string | null {
    const latest = this.view.items.findLast(
      (item) => item.kind === SCREEN_ITEM_KIND.USER,
    );
    return latest?.kind === SCREEN_ITEM_KIND.USER
      ? latest.message.platform_message_id
      : null;
  }

  /**
   * The platform message of the user message a reply quotes, which the reply names. An API
   * from before it did sends no name: the message is then read off the screen, when held.
   */
  private quoteTarget(reply: ReplyItem): string | null {
    if (!reply.quote) return null;
    if (reply.quote_platform_message_id !== undefined)
      return reply.quote_platform_message_id;
    const { id } = reply.quote;
    const found = this.view.items.find((item) => item.id === id);
    if (found?.kind !== SCREEN_ITEM_KIND.USER) {
      logger.info("reply_quote_unknown", { message_id: id });
      return null;
    }
    return found.message.platform_message_id;
  }

  private newDelivery(reply: ReplyItem): ReplyDelivery {
    const { platform, streaming } = this.options;
    const { partialReply } = this.start;
    const earlier =
      partialReply?.reply_id === reply.id
        ? {
            bubbles: partialReply.bubbles,
            openMessageIds: partialReply.open_message_ids ?? [],
          }
        : { bubbles: 0, openMessageIds: [] };
    return new ReplyDelivery(
      { live: streaming, platform, render: PLATFORM_MARKDOWN[platform] },
      this.surface,
      this.quoteTarget(reply),
      earlier,
      async (bubbles, openMessageIds) => {
        this.progress =
          bubbles > 0 || openMessageIds.length > 0
            ? {
                reply_id: reply.id,
                bubbles,
                open_message_ids: openMessageIds,
              }
            : null;
        await this.recordDelivered();
      },
    );
  }

  /** Record how far the platform has the conversation, when that moved or a reaction was placed since the last record. */
  private async recordDelivered(): Promise<void> {
    const report: DeliveryReport = {
      delivered_seq: this.deliveredThrough(),
      partial_reply: this.progress,
      placed_reactions: [...this.owedReactions.unreported],
    };
    const { recorded } = this;
    if (
      report.delivered_seq === recorded.delivered_seq &&
      samePartial(report.partial_reply, recorded.partial_reply) &&
      report.placed_reactions.length === 0
    )
      return;
    this.recorded = {
      delivered_seq: report.delivered_seq,
      partial_reply: report.partial_reply,
    };
    this.owedReactions.takeUnreported();
    await this.start.record(report);
  }

  /**
   * The newest seq at or below which every item is on the platform, never behind the last
   * record. With nothing owed it is the log head the screen reached: the next follow opens
   * after it, and the stream vouches for a head, not for an item whose entry was amended.
   */
  private deliveredThrough(): number {
    const { items } = this.view;
    const owed = items.flatMap((item) =>
      this.owes(item) ? [deliverySeq(item)] : [],
    );
    const through =
      owed.length > 0
        ? Math.min(...owed) - 1
        : Math.max(this.view.screenHead, ...items.map(deliverySeq));
    return Math.max(this.recorded.delivered_seq, through);
  }

  /** Whether an item still has something to put on the platform. */
  private owes(item: ScreenItem): boolean {
    switch (item.kind) {
      case SCREEN_ITEM_KIND.REPLY:
        return item.seq > this.floor && !this.deliveredReplies.has(item.id);
      case SCREEN_ITEM_KIND.NOTICE:
        return !this.noticed.has(item.id);
      case SCREEN_ITEM_KIND.WORK:
        return item.asking.some(
          ({ approval_id }) => !this.asked.has(approval_id),
        );
      default:
        return false;
    }
  }

  private renderTyping(): void {
    const typing = TYPING_DISPLAYS.has(this.view.display);
    if (typing && !this.stopTyping) {
      this.stopTyping = this.surface.startTyping(this.latestUserMessage());
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

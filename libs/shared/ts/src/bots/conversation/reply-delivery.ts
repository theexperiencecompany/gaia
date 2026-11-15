/**
 * One reply on the platform: the delivery state machine's state, and the
 * messages its operations opened.
 *
 * The follower feeds it the reply's bubbles as they stream (live platforms) or
 * its saved bubbles at settle (the rest), and the machine decides
 * every send, edit, delete and pause. The first message the reply opens carries
 * the native quote. A reply an earlier follow already sent the first bubbles of
 * delivers only the rest, and each bubble that goes final is reported, so a
 * restart resumes after it. The messages of the bubble still being written are
 * reported too: a restart finishes them by editing, or deletes and resends one
 * the platform will not let it edit, so no half-written bubble is left behind.
 */

import { initialDeliveryState, stepDelivery } from "../utils/bubble-delivery";
import type {
  DeliveryConfig,
  DeliveryEvent,
  DeliveryOp,
  DeliveryState,
  MessageSlot,
} from "../utils/bubble-delivery.types";
import { BUBBLE_PAUSE_MS } from "../utils/bubbles";
import { isMessageGoneError, retryAfterMs } from "../utils/delivery-errors";
import { createBotLogger, sanitizeErrorForLog } from "../utils/logger";
import { sleep } from "../utils/timeout";
import type {
  ConversationSurface,
  ReopenedBubble,
  SentBubble,
} from "./follower.types";

const logger = createBotLogger("shared", "reply-delivery");

/** How far an earlier follow got: its final bubbles, and the messages of the next one it left mid-way. */
export interface EarlierDelivery {
  bubbles: number;
  openMessageIds: readonly string[];
}

/** Told each time the final bubbles or the open bubble's messages change. */
export type DeliveredListener = (
  bubbles: number,
  openMessageIds: string[],
) => Promise<void>;

const sameIds = (a: readonly string[], b: readonly string[]): boolean =>
  a.length === b.length && a.every((id, at) => id === b[at]);

export class ReplyDelivery {
  private state: DeliveryState = initialDeliveryState();
  private readonly messages = new Map<MessageSlot, SentBubble>();
  /** Messages an earlier follow left mid-bubble, by the slot this delivery reaches them at. */
  private readonly reopened = new Map<MessageSlot, ReopenedBubble>();
  /** Slots that hold final text: every one written before the last bubble went final. */
  private readonly final = new Set<MessageSlot>();
  private readonly written = new Set<MessageSlot>();
  /** The bubbles fed last, to compare with the reply's saved ones. */
  private fed: readonly string[] = [];
  /** How many of the reply's bubbles an earlier follow already delivered. */
  private readonly skip: number;
  private reported: { bubbles: number; open: string[] };

  constructor(
    private readonly config: DeliveryConfig,
    private readonly surface: ConversationSurface,
    /** The platform message the reply's first message answers natively. */
    private readonly replyTo: string | null,
    earlier: EarlierDelivery,
    private readonly onDelivered: DeliveredListener,
  ) {
    this.skip = earlier.bubbles;
    // The machine opens the reply's messages in slot order, so the open bubble's k-th message is slot k.
    for (const [slot, id] of earlier.openMessageIds.entries()) {
      const message = surface.reopen(id);
      this.messages.set(slot, message);
      this.reopened.set(slot, message);
    }
    this.reported = {
      bubbles: earlier.bubbles,
      open: [...earlier.openMessageIds],
    };
  }

  /** The bubbles streamed into this reply so far. */
  get streamed(): readonly string[] {
    return this.fed;
  }

  /** Whether any message of this reply is on screen. */
  get opened(): boolean {
    return this.messages.size > 0;
  }

  bubbles(bubbles: readonly string[]): Promise<void> {
    this.fed = bubbles;
    return this.apply({ kind: "bubbles", bubbles: bubbles.slice(this.skip) });
  }

  tick(): Promise<void> {
    return this.apply({ kind: "tick" });
  }

  /** Deliver what is left; a reopened message the finished reply never reached is deleted. */
  async end(): Promise<void> {
    await this.apply({ kind: "end" });
    for (const [slot, message] of this.reopened) {
      // react-doctor-disable-next-line async-await-in-loop -- leftover messages are removed one platform call at a time
      if (!this.written.has(slot)) await this.discard(slot, message);
    }
    await this.report(this.reported.bubbles);
  }

  private async apply(event: DeliveryEvent): Promise<void> {
    const step = stepDelivery(this.state, event, this.config);
    this.state = step.state;
    // react-doctor-disable-next-line async-await-in-loop -- delivery ops (send, pause, edit) are an ordered script
    for (const op of step.ops) await this.run(op);
    await this.report(this.reported.bubbles);
  }

  /** Tell the listener the final bubbles and the open bubble's messages, when either moved. */
  private async report(bubbles: number): Promise<void> {
    const open = [...this.messages]
      .filter(([slot]) => !this.final.has(slot))
      .map(([, message]) => message.id);
    if (bubbles === this.reported.bubbles && sameIds(open, this.reported.open))
      return;
    this.reported = { bubbles, open };
    await this.onDelivered(bubbles, open);
  }

  private async run(op: DeliveryOp): Promise<void> {
    switch (op.kind) {
      case "pause":
        await sleep(BUBBLE_PAUSE_MS);
        return;
      case "send":
      case "edit":
        await this.editSlot(op.slot, op.text);
        this.written.add(op.slot);
        return;
      case "delivered":
        for (const slot of this.written) this.final.add(slot);
        await this.report(op.bubbles === 0 ? 0 : this.skip + op.bubbles);
        return;
      default: {
        const unhandled: never = op;
        return unhandled;
      }
    }
  }

  private async post(slot: MessageSlot, text: string): Promise<void> {
    const replyTo = this.opened || this.skip > 0 ? null : this.replyTo;
    this.messages.set(
      slot,
      await this.surface.send(this.config.render(text), replyTo),
    );
    logger.info("bubble_delivered", {
      slot,
      chars: text.length,
      quoted: replyTo !== null,
    });
  }

  /**
   * Edits a message, posting it when it is not open yet. Only a message that is
   * genuinely gone is posted again: re-sending on a rate limit or a network blip
   * delivered the reply twice. A reopened message that cannot be edited is
   * deleted first, so its half-written text does not stay above the new one.
   */
  private async editSlot(slot: MessageSlot, text: string): Promise<void> {
    const message = this.messages.get(slot);
    if (!message) {
      await this.post(slot, text);
      return;
    }
    const rendered = this.config.render(text);
    try {
      await message.edit(rendered);
    } catch (err) {
      if (isMessageGoneError(err)) {
        logger.info("stream_edit_recovered", sanitizeErrorForLog(err));
        const reopened = this.reopened.get(slot);
        if (reopened) await this.discard(slot, reopened);
        await this.post(slot, text);
        return;
      }
      const waitMs = retryAfterMs(err);
      if (waitMs !== null) await sleep(waitMs);
      try {
        await message.edit(rendered);
      } catch (retryErr) {
        logger.info("stream_edit_skipped", {
          ...sanitizeErrorForLog(retryErr),
          slot,
        });
      }
    }
  }

  /** Remove a message an earlier follow left mid-bubble; one already gone needs nothing. */
  private async discard(
    slot: MessageSlot,
    message: ReopenedBubble,
  ): Promise<void> {
    this.reopened.delete(slot);
    this.messages.delete(slot);
    try {
      await message.delete();
    } catch (err) {
      if (!isMessageGoneError(err)) throw err;
      logger.info("reopened_bubble_gone", sanitizeErrorForLog(err));
    }
  }
}

/**
 * One reply on the platform: runs the delivery machine's operations against the
 * platform and moves the reply's progress (delivery-state.ts) with each one.
 *
 * The follower feeds it the reply's bubbles as they stream (live platforms) or
 * its saved bubbles at settle (the rest), and the machine decides
 * every send, edit, delete and pause. The first message the reply opens carries
 * the native quote. A reply an earlier follow already sent the first bubbles of
 * delivers only the rest, and each bubble that goes final is recorded, so a
 * restart resumes after it. The messages of the bubble still being written are
 * recorded too: a restart finishes them by editing, or deletes and resends one
 * the platform will not let it edit, so no half-written bubble is left behind.
 *
 * A send is written ahead: its slot is recorded with no id before the platform
 * call, and the next record carries its id. A restart that finds a slot with no
 * id knows one send may be on the platform where nothing can address it, says
 * so, and sends that text again.
 */

import { initialDeliveryState, stepDelivery } from "../utils/bubble-delivery";
import type {
  DeliveryConfig,
  DeliveryEvent,
  DeliveryOp,
  DeliveryState,
  MessageSlot,
} from "../utils/bubble-delivery.types";
import {
  isMessageGoneError,
  retryTransientPlatformCall,
} from "../utils/delivery-errors";
import { createBotLogger, sanitizeErrorForLog } from "../utils/logger";
import { sleep } from "../utils/timeout";
import { wideLog } from "../utils/wide-events";
import {
  type DeliveryRecord,
  heldReopened,
  nextProgress,
  type ProgressEvent,
  type ReplyProgress,
  recordOf,
  resumeProgress,
  untouchedReopened,
} from "./delivery-state";
import type {
  ConversationSurface,
  ReopenedBubble,
  SentBubble,
} from "./follower.types";

const logger = createBotLogger("shared", "reply-delivery");

/** Told each time the record of the reply's final bubbles or open messages changes. */
export type DeliveredListener = (record: DeliveryRecord) => Promise<void>;

/** How the delivery shows text: the machine's config, plus the gap between two bubbles. */
interface ReplyDeliveryConfig extends DeliveryConfig {
  pauseMs: number;
}

const sameRecord = (a: DeliveryRecord, b: DeliveryRecord): boolean =>
  a.bubbles === b.bubbles &&
  a.openMessageIds.length === b.openMessageIds.length &&
  a.openMessageIds.every((id, at) => id === b.openMessageIds[at]);

export class ReplyDelivery {
  private text: DeliveryState = initialDeliveryState();
  private progress: ReplyProgress;
  /** The platform handle of each slot the progress names with an id. */
  private readonly handles = new Map<
    MessageSlot,
    SentBubble | ReopenedBubble
  >();
  /** The bubbles fed last, to compare with the reply's saved ones. */
  private fed: readonly string[] = [];
  /** How many of the reply's bubbles an earlier follow already delivered. */
  private readonly skip: number;
  private recorded: DeliveryRecord;

  constructor(
    private readonly config: ReplyDeliveryConfig,
    private readonly surface: ConversationSurface,
    /** The platform message the reply's first message answers natively. */
    private readonly replyTo: string | null,
    earlier: DeliveryRecord,
    private readonly onDelivered: DeliveredListener,
  ) {
    this.skip = earlier.bubbles;
    if (earlier.openMessageIds.at(-1) === null) {
      wideLog.warning("reply_send_unconfirmed", {
        slot: earlier.openMessageIds.length - 1,
      });
    }
    this.progress = resumeProgress(earlier);
    for (const [slot, state] of this.progress.slots) {
      if (state.status === "reopened")
        this.handles.set(slot, surface.reopen(state.id));
    }
    this.recorded = earlier;
  }

  /** The bubbles streamed into this reply so far. */
  get streamed(): readonly string[] {
    return this.fed;
  }

  /** Whether any message of this reply is on screen. */
  get opened(): boolean {
    return this.progress.slots.size > 0;
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
    for (const [slot] of untouchedReopened(this.progress)) {
      // react-doctor-disable-next-line async-await-in-loop -- leftover messages are removed one platform call at a time
      await this.discard(slot);
    }
    await this.record();
  }

  private async apply(event: DeliveryEvent): Promise<void> {
    const step = stepDelivery(this.text, event, this.config);
    this.text = step.state;
    // react-doctor-disable-next-line async-await-in-loop -- delivery ops (send, pause, edit) are an ordered script
    for (const op of step.ops) await this.run(op);
    await this.record();
  }

  private move(event: ProgressEvent): void {
    this.progress = nextProgress(this.progress, event);
  }

  /** Tell the listener the progress's record, when it moved since the last one. */
  private async record(): Promise<void> {
    const record = recordOf(this.progress);
    if (sameRecord(record, this.recorded)) return;
    this.recorded = record;
    await this.onDelivered(record);
  }

  private async run(op: DeliveryOp): Promise<void> {
    switch (op.kind) {
      case "pause":
        await sleep(this.config.pauseMs);
        return;
      case "send":
      case "edit":
        if (this.progress.slots.get(op.slot)?.status === "reopened")
          this.move({ kind: "held", slot: op.slot, text: op.text });
        else await this.editSlot(op.slot, op.text);
        return;
      case "delivered":
        for (const [slot, text] of heldReopened(this.progress)) {
          // react-doctor-disable-next-line async-await-in-loop -- reopened messages are edited in slot order
          await this.editSlot(slot, text);
        }
        this.move({
          kind: "delivered",
          bubbles: op.bubbles === 0 ? 0 : this.skip + op.bubbles,
        });
        await this.record();
        return;
      default: {
        const unhandled: never = op;
        return unhandled;
      }
    }
  }

  /** Send a slot's message, written ahead: the slot is recorded before the send; the next record carries its id. */
  private async post(slot: MessageSlot, text: string): Promise<void> {
    const replyTo = this.opened || this.skip > 0 ? null : this.replyTo;
    this.move({ kind: "sending", slot });
    await this.record();
    const sent = await this.surface.send(this.config.render(text), replyTo);
    this.handles.set(slot, sent);
    this.move({ kind: "sent", slot, id: sent.id });
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
   * deleted first, so its half-written text does not stay above the new one. Any
   * other refusal fails the delivery (an adapter answers "not modified" as done).
   */
  private async editSlot(slot: MessageSlot, text: string): Promise<void> {
    const message = this.handles.get(slot);
    if (!message) {
      await this.post(slot, text);
      return;
    }
    const rendered = this.config.render(text);
    try {
      await retryTransientPlatformCall(() => message.edit(rendered));
    } catch (err) {
      if (!isMessageGoneError(err)) throw err;
      logger.info("stream_edit_recovered", sanitizeErrorForLog(err));
      if (this.progress.slots.get(slot)?.status === "reopened")
        await this.discard(slot);
      else this.forget(slot);
      await this.post(slot, text);
    }
  }

  private forget(slot: MessageSlot): void {
    this.handles.delete(slot);
    this.move({ kind: "discarded", slot });
  }

  /** Remove a message an earlier follow left mid-bubble; one already gone needs nothing. */
  private async discard(slot: MessageSlot): Promise<void> {
    const message = this.handles.get(slot);
    if (!message || !("delete" in message))
      throw new Error(`slot ${slot} is not a reopened message`);
    this.forget(slot);
    try {
      await message.delete();
    } catch (err) {
      if (!isMessageGoneError(err)) throw err;
      logger.info("reopened_bubble_gone", sanitizeErrorForLog(err));
    }
  }
}

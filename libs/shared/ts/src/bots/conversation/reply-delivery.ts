/**
 * One reply on the platform: the delivery state machine's state, and the
 * messages its operations opened.
 *
 * The follower feeds it the reply's streamed text and boundaries (live
 * platforms) or its saved text at settle (the rest), and the machine decides
 * every send, edit, delete and pause. The first message the reply opens carries
 * the native quote, when the reply has one by then.
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
import { wideLog } from "../utils/wide-events";
import type { ConversationSurface, SentBubble } from "./follower.types";

const logger = createBotLogger("shared", "reply-delivery");

export class ReplyDelivery {
  private state: DeliveryState = initialDeliveryState();
  private readonly messages = new Map<MessageSlot, SentBubble>();
  /** Every response chunk fed so far, to compare with the reply's saved text. */
  private fed = "";
  /** The platform message the reply's first message answers natively. */
  private replyTo: string | null = null;

  constructor(
    private readonly config: DeliveryConfig,
    private readonly surface: ConversationSurface,
  ) {}

  /** The text streamed into this reply so far. */
  get streamed(): string {
    return this.fed;
  }

  /** Whether any message of this reply is on screen. */
  get opened(): boolean {
    return this.messages.size > 0;
  }

  /** Quote replyTo with the first message this reply opens; too late once one is open. */
  quote(replyTo: string): boolean {
    if (this.opened) return false;
    this.replyTo = replyTo;
    return true;
  }

  text(chunk: string): Promise<void> {
    this.fed += chunk;
    return this.apply({ kind: "text", chunk });
  }

  tick(): Promise<void> {
    return this.apply({ kind: "tick" });
  }

  boundary(discarded: boolean): Promise<void> {
    return this.apply({ kind: "boundary", discarded });
  }

  end(): Promise<void> {
    return this.apply({ kind: "end" });
  }

  private async apply(event: DeliveryEvent): Promise<void> {
    const step = stepDelivery(this.state, event, this.config);
    this.state = step.state;
    for (const op of step.ops) await this.run(op);
  }

  private async run(op: DeliveryOp): Promise<void> {
    switch (op.kind) {
      case "pause":
        await sleep(BUBBLE_PAUSE_MS);
        return;
      case "send":
        await this.post(op.slot, op.text);
        return;
      case "edit":
        await this.editSlot(op.slot, op.text);
        return;
      case "delete":
        await this.deleteSlot(op.slot);
        return;
      default: {
        const unhandled: never = op;
        return unhandled;
      }
    }
  }

  private async post(slot: MessageSlot, text: string): Promise<void> {
    const replyTo = this.opened ? null : this.replyTo;
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
   * delivered the reply twice.
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

  private async deleteSlot(slot: MessageSlot): Promise<void> {
    const message = this.messages.get(slot);
    this.messages.delete(slot);
    if (!message) return;
    if (!message.delete) {
      throw new Error(
        `${this.config.platform} cannot delete a bot message, so it must not stream`,
      );
    }
    try {
      await message.delete();
    } catch (err) {
      // The retracted text stays on screen; nothing else can take it back.
      wideLog.warning("bubble_delete_failed", {
        ...sanitizeErrorForLog(err),
        slot,
      });
    }
  }
}

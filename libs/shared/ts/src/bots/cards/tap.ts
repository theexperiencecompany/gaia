/**
 * The one path every platform takes when a user taps a card's invoke button:
 * perform the action through the API, then let the adapter show the outcome
 * and re-render the card as the API now has it.
 *
 * @module
 */
import type { BotCardActionResult } from "../../api/generated";
import type { GaiaClient } from "../api";
import type { PlatformName } from "../types";
import { recordBotFailure } from "../utils/failure-reasons";
import { hashLogIdentifier } from "../utils/logger";
import { wideLog, withWideEvent } from "../utils/wide-events";
import { cardAfterTap } from "./registry";
import type { Card } from "./types";

/** Shown when the API could not be reached or refused the call outright. */
const CARD_TAP_FAILED_MESSAGE =
  "Something went wrong with that button. Please try again.";

/** How a tap ended, as the API reports it ("failed" when the API could not be reached). */
export type CardTapOutcome = BotCardActionResult["outcome"];

export interface CardTapResult {
  outcome: CardTapOutcome;
  /** User-facing outcome line, shown to the tapper. */
  message: string;
  /**
   * The tapped card as it stands after the tap, to replace the tapped message
   * with; `null` leaves the message as it is (an expired or failed tap).
   */
  card: Card | null;
}

export interface CardTap {
  gaia: GaiaClient;
  platform: PlatformName;
  platformUserId: string;
  actionId: string;
  /** Acknowledges the tap within the platform's deadline, before the API call. */
  acknowledge?: () => Promise<void>;
  /** Shows the result: tells the tapper the outcome and updates the card message. */
  show: (result: CardTapResult) => Promise<void>;
}

async function performCardTap(tap: CardTap): Promise<CardTapResult> {
  try {
    const result = await tap.gaia.performCardAction(
      tap.platform,
      tap.platformUserId,
      tap.actionId,
    );
    const card = result.card ? cardAfterTap(result.card, tap.actionId) : null;
    wideLog.setNs("card_action", {
      result: result.outcome,
      tool_name: result.card?.tool_name,
      card_updated: card !== null,
    });
    if (result.card && !card) {
      // The message keeps its old buttons; a second tap gets "already done".
      wideLog.warning("card_after_tap_unmatched", {
        tool_name: result.card.tool_name,
      });
    }
    return { outcome: result.outcome, message: result.message, card };
  } catch (error) {
    recordBotFailure("card_action_failed", error);
    return { outcome: "failed", message: CARD_TAP_FAILED_MESSAGE, card: null };
  }
}

/**
 * Handles one tap as its own unit of work. Never throws: a failure is recorded
 * on the event and, where the API call itself failed, shown to the user as
 * {@link CARD_TAP_FAILED_MESSAGE}.
 */
export async function handleCardTap(tap: CardTap): Promise<void> {
  const userHash = hashLogIdentifier(tap.platformUserId);
  await withWideEvent(
    "card_action",
    {
      platform: tap.platform,
      component: "card-tap",
      operation: "card_action",
      user_hash: userHash,
    },
    async () => {
      try {
        await tap.acknowledge?.();
      } catch (error) {
        recordBotFailure("card_tap_ack_failed", error);
        return;
      }
      // Acts for the user (approves, sends their email): leave a trail.
      wideLog.audit("card_action_requested", { user_hash: userHash });
      const result = await performCardTap(tap);
      try {
        await tap.show(result);
      } catch (error) {
        recordBotFailure("card_tap_update_failed", error);
      }
    },
  );
}

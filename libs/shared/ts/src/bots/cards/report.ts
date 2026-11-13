/**
 * Reports the tool cards a user was shown back to the API, which records them in
 * the agent's conversation: the agent then knows exactly what is on the user's
 * screen, including a card that failed to send.
 *
 * @module
 */
import type { ReportedBotCard } from "../../api/generated";
import type { GaiaClient } from "../api";
import type { PlatformName } from "../types";
import { createBotLogger } from "../utils/logger";

/** The API accepts at most this many cards per report (`BotCardsReport.cards`). */
const MAX_CARDS_PER_REPORT = 20;

/** Fire-and-forget: never throws into the delivery path that calls it. */
export type ReportCardDeliveries = (
  platformUserId: string,
  conversationId: string,
  cards: ReportedBotCard[],
) => void;

export function createCardDeliveryReporter(
  gaia: GaiaClient,
  platform: PlatformName,
): ReportCardDeliveries {
  const logger = createBotLogger(platform, "card-delivery");
  return (platformUserId, conversationId, cards) => {
    if (cards.length === 0) return;
    // An async wrapper, not a bare .catch(): a synchronous throw from the client
    // must become a logged rejection too, never an exception in the caller.
    const send = async (): Promise<void> => {
      for (let i = 0; i < cards.length; i += MAX_CARDS_PER_REPORT) {
        await gaia.reportCardsDelivered(
          { platform, platformUserId },
          conversationId,
          cards.slice(i, i + MAX_CARDS_PER_REPORT),
        );
      }
    };
    send().catch((error: unknown) => {
      logger.error(
        "card_delivery_report_failed",
        {
          card_count: cards.length,
          tool_names: cards.map((card) => card.tool_name).join(","),
        },
        error,
      );
    });
  };
}

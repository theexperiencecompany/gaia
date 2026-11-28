/**
 * The usage limit a run hit, as a chat platform shows it: the server streams a
 * rate_limit_data card the web renders as a card, and a bot words it as one line
 * with the upgrade link.
 */

import type { RateLimitCardData, ToolTimeline } from "../../api/generated";
import { cardData } from "../../conversation/selectors";
import type { FollowLinks } from "./follower.types";

/** The tool_name of a usage limit's card. */
export const RATE_LIMIT_TOOL = "rate_limit_data";
const TOP_PLAN = "pro";

/** What the notice reads of the card; message is absent on cards stored before it existed. */
type RateLimitNotice = Pick<RateLimitCardData, "feature" | "current_plan"> &
  Partial<Pick<RateLimitCardData, "message">>;

const isRateLimitData = (data: unknown): data is RateLimitNotice =>
  typeof data === "object" &&
  data !== null &&
  "feature" in data &&
  typeof data.feature === "string" &&
  "current_plan" in data &&
  typeof data.current_plan === "string";

const noticeLine = (card: RateLimitNotice, pricingUrl: string): string => {
  // The card's own message names the wall that actually bound, as on web.
  const said = card.message
    ? `⏳ ${card.message}`
    : `⏳ You've reached your ${card.feature.replaceAll("_", " ")} limit. Please try again later.`;
  return card.current_plan === TOP_PLAN
    ? said
    : `${said} [Upgrade to Pro](${pricingUrl}) for higher limits.`;
};

/** One line per usage limit in the timeline, in the order they were hit. */
export function rateLimitNotices(
  timeline: ToolTimeline,
  links: FollowLinks,
): string[] {
  return cardData(timeline, RATE_LIMIT_TOOL).flatMap((card) =>
    isRateLimitData(card) ? [noticeLine(card, links.pricing)] : [],
  );
}

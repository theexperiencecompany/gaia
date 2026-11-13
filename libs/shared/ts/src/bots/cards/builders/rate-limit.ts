import type { RateLimitData } from "../../../chat/types";
import type { Card } from "../types";

const UNNAMED_FEATURE = "this feature";
const UPGRADE_LABEL = "Upgrade to Pro";
const LIMIT_TITLE = "Limit reached";

/** A limit the user hit, with the upgrade link when one applies to them. */
export function buildRateLimitCards(data: RateLimitData): Card[] {
  const feature = data.feature
    ? data.feature.replaceAll("_", " ")
    : UNNAMED_FEATURE;
  const message =
    data.message ??
    `You've reached your ${feature} limit. Please try again later.`;
  const card: Card = {
    title: LIMIT_TITLE,
    accent: "warning",
    blocks: [{ kind: "text", markdown: message }],
    actions: data.upgrade_url
      ? [{ kind: "link", label: UPGRADE_LABEL, url: data.upgrade_url }]
      : [],
  };
  return [card];
}

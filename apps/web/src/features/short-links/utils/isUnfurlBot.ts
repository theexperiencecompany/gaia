import { LINK_CONSTANTS } from "../link-constants.generated";

/** Whether a request comes from a bot building a chat preview, which gets the page's metadata only. */
export function isUnfurlBot(userAgent: string | null): boolean {
  if (!userAgent) return false;
  const agent = userAgent.toLowerCase();
  return LINK_CONSTANTS.unfurlBotUserAgentMarkers.some((marker) =>
    agent.includes(marker),
  );
}

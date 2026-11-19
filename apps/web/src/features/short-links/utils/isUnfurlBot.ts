import { UNFURL_BOT_USER_AGENT_MARKERS } from "../constants";

/** Whether a request comes from a bot building a chat preview, which gets the page's metadata only. */
export function isUnfurlBot(userAgent: string | null): boolean {
  if (!userAgent) return false;
  const agent = userAgent.toLowerCase();
  return UNFURL_BOT_USER_AGENT_MARKERS.some((marker) => agent.includes(marker));
}

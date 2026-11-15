/**
 * How each platform shows a reply. Live platforms (Telegram, Slack) stream it
 * into edited messages, throttled to the edit interval; the rest send each
 * message once the reply is final.
 */

import type { PlatformName } from "../types";
import type { ConversationSurface, StreamingOptions } from "./follower.types";

export const STREAMING_DEFAULTS: Record<PlatformName, StreamingOptions> = {
  discord: { editIntervalMs: 1200, streaming: false, platform: "discord" },
  slack: { editIntervalMs: 1500, streaming: true, platform: "slack" },
  telegram: { editIntervalMs: 1000, streaming: true, platform: "telegram" },
  whatsapp: { editIntervalMs: 2000, streaming: false, platform: "whatsapp" },
  imessage: { editIntervalMs: 2000, streaming: false, platform: "imessage" },
};

/** The reopen of a platform that sends each message final: no follow there leaves one mid-bubble. */
export function neverReopened(
  platform: PlatformName,
): ConversationSurface["reopen"] {
  return () => {
    throw new Error(
      `${platform} never streams a reply, so no message is left mid-bubble to reopen`,
    );
  };
}

/**
 * How each platform shows a reply. Live platforms (Telegram, Slack) stream it
 * into edited messages, throttled to the edit interval; the rest send each
 * message once the reply is final.
 */

import type { PlatformName } from "../types";
import { BUBBLE_PAUSE_MS } from "../utils/bubbles";
import type { ConversationSurface, StreamingOptions } from "./follower.types";

export const STREAMING_DEFAULTS: Record<PlatformName, StreamingOptions> = {
  discord: {
    editIntervalMs: 1200,
    streaming: false,
    platform: "discord",
    bubblePauseMs: BUBBLE_PAUSE_MS,
  },
  slack: {
    editIntervalMs: 1500,
    streaming: true,
    platform: "slack",
    bubblePauseMs: BUBBLE_PAUSE_MS,
  },
  telegram: {
    editIntervalMs: 1000,
    streaming: true,
    platform: "telegram",
    bubblePauseMs: BUBBLE_PAUSE_MS,
  },
  whatsapp: {
    editIntervalMs: 2000,
    streaming: false,
    platform: "whatsapp",
    bubblePauseMs: BUBBLE_PAUSE_MS,
  },
  imessage: {
    editIntervalMs: 2000,
    streaming: false,
    platform: "imessage",
    bubblePauseMs: BUBBLE_PAUSE_MS,
  },
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

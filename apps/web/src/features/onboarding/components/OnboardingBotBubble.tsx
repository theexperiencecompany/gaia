/**
 * One GAIA chat bubble with the onboarding defaults (read-only, no actions).
 */

import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";

import { BOT_BUBBLE_DEFAULTS } from "../constants/bubbleDefaults";

interface OnboardingBotBubbleProps {
  text: string;
  /** Seconds between consecutive lines landing (chat's quick ripple if unset). */
  partStaggerSeconds?: number;
  partDurationSeconds?: number;
}

export function OnboardingBotBubble({
  text,
  partStaggerSeconds,
  partDurationSeconds,
}: OnboardingBotBubbleProps) {
  // On a phone the chat bubble's 80% cap wastes the little width there is;
  // the onboarding column is already narrow, so let the bubble fill it.
  return (
    <div className="max-sm:[&_.chat_bubble]:max-w-full">
      <ChatBubbleBot
        {...BOT_BUBBLE_DEFAULTS}
        text={text}
        partStaggerSeconds={partStaggerSeconds}
        partDurationSeconds={partDurationSeconds}
      />
    </div>
  );
}

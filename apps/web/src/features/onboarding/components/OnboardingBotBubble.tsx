/**
 * One GAIA chat bubble with the onboarding defaults (read-only, no actions).
 */

import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";
import type { PartChoreography } from "@/features/chat/utils/messageBreakUtils";
import { useIsMobile } from "@/hooks/ui/useMobile";

import { BOT_BUBBLE_DEFAULTS } from "../constants/bubbleDefaults";

interface OnboardingBotBubbleProps {
  text: string;
  /** How the lines land; chat's quick ripple if unset. */
  partChoreography?: PartChoreography;
}

export function OnboardingBotBubble({
  text,
  partChoreography,
}: OnboardingBotBubbleProps) {
  // On a phone the chat bubble's 80% cap wastes the little width there is;
  // the onboarding column is already narrow, so let a long line use all of it, drop
  // the avatar lane (and the logo that sits in it) and tighten the right pad.
  const isMobile = useIsMobile();
  return (
    <div className="max-sm:[&_.imessage-bubble]:max-w-full max-sm:[&_.imessage-bubble]:pr-3">
      <ChatBubbleBot
        {...BOT_BUBBLE_DEFAULTS}
        text={text}
        partChoreography={partChoreography}
        hideAvatar={isMobile}
      />
    </div>
  );
}

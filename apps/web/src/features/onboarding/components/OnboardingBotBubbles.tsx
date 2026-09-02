/**
 * GAIA's side of an onboarding turn. `OnboardingBotBubble` is one chat bubble
 * with the onboarding defaults; `OnboardingBotBubbles` joins several lines
 * with the same break token chat replies use, so a stage's copy renders as
 * chat does (one avatar, a stacked group) rather than as separate messages.
 */

import { NEW_MESSAGE_BREAK_TOKEN } from "@shared/utils";

import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";

import { BOT_BUBBLE_DEFAULTS } from "../constants/bubbleDefaults";

export function OnboardingBotBubble({ text }: { text: string }) {
  return <ChatBubbleBot {...BOT_BUBBLE_DEFAULTS} text={text} />;
}

export function OnboardingBotBubbles({ lines }: { lines: string[] }) {
  return <OnboardingBotBubble text={lines.join(NEW_MESSAGE_BREAK_TOKEN)} />;
}

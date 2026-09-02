/**
 * Presentational transcript renderer. Given a Q&A `messages` list, paints
 * alternating bot/user chat bubbles. No state, no effects.
 */

import { NEW_MESSAGE_BREAK_TOKEN } from "@shared/utils";
import * as m from "motion/react-m";
import { memo } from "react";

import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";
import ChatBubbleUser from "@/features/chat/components/bubbles/user/ChatBubbleUser";

import {
  BOT_BUBBLE_DEFAULTS,
  USER_BUBBLE_DEFAULTS,
} from "../constants/bubbleDefaults";
import { EASE_OUT_QUART } from "../constants/motion";
import type { Message } from "../types";

export function OnboardingBotBubble({ text }: { text: string }) {
  return <ChatBubbleBot {...BOT_BUBBLE_DEFAULTS} text={text} />;
}

/** GAIA's side of a stage: one message, split into bubbles by the same
 * break token chat replies use, so it renders as chat does (one avatar, a
 * stacked group) rather than as separate messages. */
export function OnboardingBotBubbles({ lines }: { lines: string[] }) {
  return <OnboardingBotBubble text={lines.join(NEW_MESSAGE_BREAK_TOKEN)} />;
}

function OnboardingUserBubble({ text }: { text: string }) {
  return <ChatBubbleUser {...USER_BUBBLE_DEFAULTS} text={text} />;
}

interface OnboardingMessagesProps {
  messages: Message[];
}

function OnboardingMessagesImpl({ messages }: OnboardingMessagesProps) {
  return (
    <>
      {messages.map((message, index) => (
        <m.div
          key={message.id}
          className="mb-4"
          initial={{ opacity: 0, y: 15 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{
            duration: 0.4,
            ease: EASE_OUT_QUART,
            delay: index * 0.05,
          }}
        >
          {message.type === "bot" ? (
            <OnboardingBotBubble text={message.content} />
          ) : (
            <div className="flex items-end justify-end gap-0">
              <OnboardingUserBubble text={message.content} />
            </div>
          )}
        </m.div>
      ))}
    </>
  );
}

export const OnboardingMessages = memo(OnboardingMessagesImpl);

/**
 * Presentational transcript renderer. Given a Q&A `messages` list, paints
 * alternating bot/user chat bubbles. No state, no effects.
 */

import { NEW_MESSAGE_BREAK_TOKEN } from "@shared/utils";
import * as m from "motion/react-m";
import { memo } from "react";
import ChatBubbleUser from "@/features/chat/components/bubbles/user/ChatBubbleUser";
import { USER_BUBBLE_DEFAULTS } from "../constants/bubbleDefaults";
import { EASE_OUT_QUART } from "../constants/motion";
import { questionRevealKey } from "../state/paceStore";
import type { Message } from "../types";
import { OnboardingBotBubble } from "./OnboardingBotBubble";
import { OnboardingBotBubbles } from "./OnboardingBotBubbles";

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
            // The question being asked right now is paced out like a person
            // typing; answered turns are history and render at once.
            index === messages.length - 1 ? (
              <OnboardingBotBubbles
                lines={message.content.split(NEW_MESSAGE_BREAK_TOKEN)}
                revealKey={questionRevealKey(message.id)}
              />
            ) : (
              <OnboardingBotBubble text={message.content} />
            )
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

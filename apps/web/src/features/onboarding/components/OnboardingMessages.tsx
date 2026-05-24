/**
 * Presentational transcript renderer. Given a Q&A `messages` list and an
 * optional `processingChecklist` slot, paints alternating bot/user chat
 * bubbles and — when supplied — appends the checklist beneath the last
 * bot bubble. No state, no effects.
 */

import * as m from "motion/react-m";
import { memo, type ReactNode } from "react";

import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";
import ChatBubbleUser from "@/features/chat/components/bubbles/user/ChatBubbleUser";

import {
  BOT_BUBBLE_DEFAULTS,
  USER_BUBBLE_DEFAULTS,
} from "../constants/bubbleDefaults";
import { EASE_OUT_QUART } from "../constants/motion";
import type { Message } from "../types";

function OnboardingBotBubble({
  text,
  children,
}: {
  text: string;
  children?: ReactNode;
}) {
  return (
    <ChatBubbleBot {...BOT_BUBBLE_DEFAULTS} text={text}>
      {children}
    </ChatBubbleBot>
  );
}

function OnboardingUserBubble({ text }: { text: string }) {
  return <ChatBubbleUser {...USER_BUBBLE_DEFAULTS} text={text} />;
}

interface OnboardingMessagesProps {
  messages: Message[];
  messagesEndRef?: React.RefObject<HTMLDivElement | null>;
  processingChecklist?: ReactNode;
}

function OnboardingMessagesImpl({
  messages,
  messagesEndRef,
  processingChecklist,
}: OnboardingMessagesProps) {
  return (
    <>
      {messages.map((message, index) => {
        const isLastBot =
          message.type === "bot" && index === messages.length - 1;
        return (
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
              <OnboardingBotBubble text={message.content}>
                {isLastBot && processingChecklist && (
                  <m.div
                    className="ml-10.75"
                    initial={{ opacity: 0, y: 15 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{
                      duration: 0.5,
                      ease: "easeOut",
                      delay: 0.3,
                    }}
                  >
                    {processingChecklist}
                  </m.div>
                )}
              </OnboardingBotBubble>
            ) : (
              <div className="flex items-end justify-end gap-0">
                <OnboardingUserBubble text={message.content} />
              </div>
            )}
          </m.div>
        );
      })}

      {messagesEndRef && <div ref={messagesEndRef} />}
    </>
  );
}

export const OnboardingMessages = memo(OnboardingMessagesImpl);

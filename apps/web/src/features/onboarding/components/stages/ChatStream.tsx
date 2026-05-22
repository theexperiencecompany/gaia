/**
 * Renders the live onboarding chat stream (user + bot bubbles plus the thinking
 * indicator). Shared by the `chat` stage and the run-now todo demo, so it lives
 * in its own file rather than inside Chat.tsx.
 */

"use client";

import * as m from "motion/react-m";
import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";
import ChatBubbleUser from "@/features/chat/components/bubbles/user/ChatBubbleUser";
import { LoadingIndicator } from "@/features/chat/components/interface/LoadingIndicator";
import {
  BOT_BUBBLE_DEFAULTS,
  USER_BUBBLE_DEFAULTS,
} from "../../constants/bubbleDefaults";
import { MOTION_STREAM_MESSAGE } from "../../constants/motion";
import type { UseOnboardingChatReturn } from "../../hooks/useOnboardingChat";

const RUN_NOW_PREFIX = "Execute this todo for me: ";

export function OnboardingChatStream({
  chat,
  hideRunNowUserMessage = false,
  hideBotAvatar = false,
}: {
  chat: UseOnboardingChatReturn;
  hideRunNowUserMessage?: boolean;
  hideBotAvatar?: boolean;
}) {
  const visibleMessages = hideRunNowUserMessage
    ? chat.streamMessages.filter(
        (msg) =>
          !(
            msg.role === "user" &&
            typeof msg.content === "string" &&
            msg.content.startsWith(RUN_NOW_PREFIX)
          ),
      )
    : chat.streamMessages;
  return (
    <>
      {visibleMessages.map((msg) => (
        <m.div key={msg.id} {...MOTION_STREAM_MESSAGE}>
          {msg.role === "user" ? (
            <ChatBubbleUser
              {...USER_BUBBLE_DEFAULTS}
              text={msg.content}
              message_id={msg.id}
              date={msg.createdAt.toISOString()}
              fileData={msg.fileData}
            />
          ) : (
            <ChatBubbleBot
              {...BOT_BUBBLE_DEFAULTS}
              text={msg.content}
              message_id={msg.id}
              loading={msg.status === "sending"}
              tool_data={msg.tool_data ?? undefined}
              todo_progress={msg.todo_progress ?? undefined}
              memory_data={msg.memory_data ?? undefined}
              image_data={msg.image_data ?? undefined}
              date={msg.createdAt.toISOString()}
              hideAvatar={hideBotAvatar}
            />
          )}
        </m.div>
      ))}

      {chat.isChatSending &&
        !visibleMessages.some(
          (msg) => msg.role === "assistant" && msg.content,
        ) && (
          <LoadingIndicator
            loadingText={
              hideRunNowUserMessage
                ? "Auto-executing todo…"
                : "GAIA is thinking…"
            }
            loadingTextKey={0}
            noPadding={hideRunNowUserMessage}
          />
        )}
    </>
  );
}

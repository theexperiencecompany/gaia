/**
 * `chat` stage. Renders the welcome conversation stream followed by the holo
 * card reveal. The composer is always a "Continue to GAIA" CTA — the onboarding
 * first message intentionally closes its own loop, so there is no free-chat
 * input here. Active once the backend has produced `first_message_conversation_id`.
 */

"use client";

import * as m from "motion/react-m";
import type { Dispatch } from "react";
import { useEffect } from "react";
import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";
import ChatBubbleUser from "@/features/chat/components/bubbles/user/ChatBubbleUser";
import { LoadingIndicator } from "@/features/chat/components/interface/LoadingIndicator";
import {
  BOT_BUBBLE_DEFAULTS,
  USER_BUBBLE_DEFAULTS,
} from "../../constants/bubbleDefaults";
import {
  MOTION_COMPOSER_CTA,
  MOTION_FADE_UP_LARGE,
  MOTION_STREAM_MESSAGE,
} from "../../constants/motion";
import {
  type UseOnboardingChatReturn,
  useOnboardingChat,
} from "../../hooks/useOnboardingChat";
import type { Action, OnboardingState } from "../../state/types";
import { OnboardingCTAButton } from "../OnboardingCTAButton";
import { HoloCardReveal } from "../reveal/HoloCardReveal";

interface ChatProps {
  state: OnboardingState;
  dispatch: Dispatch<Action>;
  chat: UseOnboardingChatReturn;
}

export interface OnboardingChatStages {
  welcome: UseOnboardingChatReturn;
  todoDemo: UseOnboardingChatReturn;
}

export function useChatStage(
  state: OnboardingState,
  dispatch: Dispatch<Action>,
): OnboardingChatStages {
  const welcomeConvoId = state.server?.first_message_conversation_id ?? null;
  const todoDemoConvoId = state.todoExecutionConvoId;
  const pendingTodoMessage = state.todoExecutionMessage;

  const welcome = useOnboardingChat(welcomeConvoId, null);
  const todoDemo = useOnboardingChat(todoDemoConvoId, pendingTodoMessage);

  useEffect(() => {
    if (!pendingTodoMessage || !todoDemoConvoId) return;
    dispatch({ type: "clearTodoExecutionMessage" });
  }, [pendingTodoMessage, todoDemoConvoId, dispatch]);

  return { welcome, todoDemo };
}

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

export function Chat({ state }: Omit<ChatProps, "dispatch" | "chat">) {
  const showHolo = state.server?.has_personalization && state.server;
  if (!showHolo || !state.server) return null;

  const firstMessage = state.server.first_message;

  return (
    <m.div className="mt-4 space-y-4" {...MOTION_FADE_UP_LARGE}>
      {firstMessage && (
        <ChatBubbleBot
          {...BOT_BUBBLE_DEFAULTS}
          text={firstMessage}
          message_id="onboarding-first-message"
          loading={false}
          date={new Date().toISOString()}
        />
      )}
      <div className="my-4">
        <HoloCardReveal personalizationData={state.server} />
      </div>
    </m.div>
  );
}

export function ChatComposer({ state }: Omit<ChatProps, "dispatch" | "chat">) {
  const welcomeConvoId = state.server?.first_message_conversation_id;
  const href = welcomeConvoId ? `/c/${welcomeConvoId}` : "/c";
  return (
    <m.div className="flex justify-center pb-2" {...MOTION_COMPOSER_CTA}>
      <OnboardingCTAButton href={href}>Continue to GAIA</OnboardingCTAButton>
    </m.div>
  );
}

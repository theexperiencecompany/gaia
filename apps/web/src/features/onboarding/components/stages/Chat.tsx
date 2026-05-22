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
import { BOT_BUBBLE_DEFAULTS } from "../../constants/bubbleDefaults";
import {
  MOTION_COMPOSER_CTA,
  MOTION_FADE_UP_LARGE,
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

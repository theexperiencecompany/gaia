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
  /** Live welcome conversation — seeded by the backend, lands the user in
   *  `/c/{first_message_conversation_id}` after onboarding. Never receives
   *  the run-now demo. */
  welcome: UseOnboardingChatReturn;
  /** Throwaway conversation that runs the in-place run-now todo demo. Kept
   *  separate from `welcome` so the executed turn doesn't appear in the
   *  post-onboarding chat. */
  todoDemo: UseOnboardingChatReturn;
}

/**
 * Page-level hook that wires up two independent chat streams: the welcome
 * conversation (for the final `chat` stage) and a throwaway conversation
 * for the run-now todo demo. Splitting them stops the run-now turn from
 * bleeding into the welcome conversation when the user clicks
 * "Continue to GAIA". Also clears `todoExecutionMessage` once the demo
 * conversation has consumed it so a remount can't re-queue.
 */
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

/** Shared stream renderer — used by both the in-place todo demo inside
 *  `revealTodos` and by the final `chat` stage. When `hideRunNowUserMessage`
 *  is true, the auto-sent "Execute this todo for me: ..." user turn is
 *  filtered out entirely (the demo container shows a static "selected todo"
 *  indicator instead). */
export function OnboardingChatStream({
  chat,
  hideRunNowUserMessage = false,
}: {
  chat: UseOnboardingChatReturn;
  hideRunNowUserMessage?: boolean;
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

/** Composer for the `chat` stage. Always renders the "Continue to GAIA" CTA —
 *  the onboarding chat stage ends with a closed-loop message (no question), so
 *  the user's only forward move is into the full chat experience. The CTA
 *  lands the user inside the seeded welcome conversation when available so
 *  the post-onboarding welcome UI shows up immediately. */
export function ChatComposer({ state }: Omit<ChatProps, "dispatch" | "chat">) {
  const welcomeConvoId = state.server?.first_message_conversation_id;
  const href = welcomeConvoId ? `/c/${welcomeConvoId}` : "/c";
  return (
    <m.div className="flex justify-center pb-2" {...MOTION_COMPOSER_CTA}>
      <OnboardingCTAButton href={href}>Continue to GAIA</OnboardingCTAButton>
    </m.div>
  );
}

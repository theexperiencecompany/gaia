/**
 * `chat` stage. Renders the welcome conversation stream above an inline
 * holo card reveal, plus a free-chat composer. Active once the backend has
 * produced `first_message_conversation_id`.
 */

"use client";

import { m } from "motion/react";
import type { Dispatch } from "react";
import { useCallback, useEffect, useRef } from "react";
import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";
import ChatBubbleUser from "@/features/chat/components/bubbles/user/ChatBubbleUser";
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
import { OnboardingInput } from "../OnboardingInput";
import { HoloCardReveal } from "../reveal/HoloCardReveal";

const TYPING_DOT_CLASSES = [
  "[animation-delay:0ms]",
  "[animation-delay:150ms]",
  "[animation-delay:300ms]",
] as const;

interface ChatProps {
  state: OnboardingState;
  dispatch: Dispatch<Action>;
  chat: UseOnboardingChatReturn;
}

/**
 * Shared hook the page calls once per render so Content and Composer read
 * from the same chat stream. Also clears the pending todo execution message
 * once the conversation is wired so a remount can't re-queue it. The
 * underlying `useOnboardingChat` already dedups the actual send.
 */
export function useChatStage(
  state: OnboardingState,
  dispatch: Dispatch<Action>,
): UseOnboardingChatReturn {
  const conversationId = state.server?.first_message_conversation_id ?? null;
  const pendingTodoMessage = state.todoExecutionMessage;

  const chat = useOnboardingChat(conversationId, pendingTodoMessage);

  useEffect(() => {
    if (!pendingTodoMessage || !conversationId) return;
    dispatch({ type: "clearTodoExecutionMessage" });
  }, [pendingTodoMessage, conversationId, dispatch]);

  return chat;
}

/** Stream + holo reveal content for the `chat` stage. */
export function Chat({ state, chat }: Omit<ChatProps, "dispatch">) {
  const showHolo = state.server?.has_personalization && state.server;

  return (
    <m.div className="mt-4 space-y-4" {...MOTION_FADE_UP_LARGE}>
      {showHolo && state.server && (
        <div className="my-4">
          <HoloCardReveal personalizationData={state.server} />
        </div>
      )}

      {chat.streamMessages.map((msg) => (
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
        !chat.streamMessages.some(
          (m) => m.role === "assistant" && m.content,
        ) && (
          <m.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="flex items-center gap-2 pl-1"
          >
            <div className="min-w-10 shrink-0" />
            <div className="flex gap-1.5">
              {TYPING_DOT_CLASSES.map((delay) => (
                <span
                  key={delay}
                  className={`inline-block size-1.5 animate-bounce rounded-full bg-zinc-500 ${delay}`}
                />
              ))}
            </div>
          </m.div>
        )}
    </m.div>
  );
}

/** Free-chat composer for the `chat` stage; submits via `chat.sendChatMessage`. */
export function ChatComposer({ chat }: Omit<ChatProps, "state" | "dispatch">) {
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFreeChatSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      const trimmed = chat.chatInputValue.trim();
      if (!trimmed) return;
      void chat.sendChatMessage(trimmed);
    },
    [chat],
  );

  if (chat.isTodoExecutionDone) {
    return (
      <m.div className="flex justify-center pb-2" {...MOTION_COMPOSER_CTA}>
        <OnboardingCTAButton href="/c">Continue to GAIA</OnboardingCTAButton>
      </m.div>
    );
  }

  return (
    <OnboardingInput
      mode="freeChat"
      inputRef={inputRef}
      freeChatValue={chat.chatInputValue}
      isSending={chat.isChatSending}
      onFreeChatChange={chat.setChatInputValue}
      onFreeChatSubmit={handleFreeChatSubmit}
    />
  );
}

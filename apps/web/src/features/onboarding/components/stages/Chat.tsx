/**
 * `chat` stage. Renders the welcome conversation stream followed by the holo
 * card reveal. The composer is always a "Continue to GAIA" CTA — the onboarding
 * first message intentionally closes its own loop, so there is no free-chat
 * input here. Active once the backend has produced `first_message_conversation_id`.
 */

"use client";

import { Mail01Icon } from "@icons";
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

const RUN_NOW_PREFIX = "Execute this todo for me: ";

interface TodoRunNowCardProps {
  title: string;
  sourceEmail: { sender: string; subject: string } | null;
}

/**
 * Custom user-side bubble shown in place of the raw "Execute this todo for me:
 * X" auto-send. Surfaces the todo title prominently and the source email as
 * a small hint chip below — so the user sees a meaningful card instead of a
 * machine-generated sentence.
 */
function TodoRunNowCard({ title, sourceEmail }: TodoRunNowCardProps) {
  return (
    <div className="flex justify-end pr-2">
      <div className="max-w-[80%] rounded-2xl bg-zinc-800 p-4">
        <div className="text-xs font-medium tracking-wide text-zinc-400 uppercase">
          Run now
        </div>
        <div className="mt-1 text-sm text-zinc-100">{title}</div>
        {sourceEmail && (
          <div className="mt-3 flex items-start gap-2 rounded-xl bg-zinc-900 p-3">
            <Mail01Icon className="mt-0.5 size-3.5 shrink-0 text-zinc-500" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-xs text-zinc-400">
                {sourceEmail.sender}
              </div>
              <div className="truncate text-xs text-zinc-500">
                {sourceEmail.subject}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/** Shared stream renderer — used by both the in-place todo demo inside
 *  `revealTodos` and by the final `chat` stage. When a user message matches
 *  the Run Now auto-send shape, render the custom `TodoRunNowCard` instead
 *  of the raw text bubble. */
export function OnboardingChatStream({
  chat,
  todoOverride,
}: {
  chat: UseOnboardingChatReturn;
  todoOverride?: TodoRunNowCardProps | null;
}) {
  return (
    <>
      {chat.streamMessages.map((msg) => {
        const isRunNowMessage =
          msg.role === "user" &&
          typeof msg.content === "string" &&
          msg.content.startsWith(RUN_NOW_PREFIX);
        return (
          <m.div key={msg.id} {...MOTION_STREAM_MESSAGE}>
            {msg.role === "user" ? (
              isRunNowMessage && todoOverride ? (
                <TodoRunNowCard
                  title={todoOverride.title}
                  sourceEmail={todoOverride.sourceEmail}
                />
              ) : (
                <ChatBubbleUser
                  {...USER_BUBBLE_DEFAULTS}
                  text={msg.content}
                  message_id={msg.id}
                  date={msg.createdAt.toISOString()}
                  fileData={msg.fileData}
                />
              )
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
        );
      })}

      {chat.isChatSending &&
        !chat.streamMessages.some(
          (msg) => msg.role === "assistant" && msg.content,
        ) && (
          <LoadingIndicator
            loadingText={
              todoOverride ? "Auto-executing todo…" : "GAIA is thinking…"
            }
            loadingTextKey={0}
          />
        )}
    </>
  );
}

/** Final `chat` stage content. The run-now demo transcript (when present)
 *  lives in the persistent timeline above, so this stage owns only the closing
 *  ceremony: the holo personalization card. The composer surfaces the
 *  "Continue to GAIA" CTA. */
export function Chat({ state }: Omit<ChatProps, "dispatch" | "chat">) {
  const showHolo = state.server?.has_personalization && state.server;
  if (!showHolo || !state.server) return null;

  return (
    <m.div className="mt-4 space-y-4" {...MOTION_FADE_UP_LARGE}>
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

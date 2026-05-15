/**
 * `revealTodos` stage. Active once `onboarding_todos` is non-empty and the
 * user hasn't acked yet.
 *
 * Two sub-states:
 * - **Grid mode** (default): show the suggested todos. User can click "Run"
 *   on one (→ `executeTodo`, flips into stream mode) or "I'll do it later"
 *   (→ `ackTodos`, advances to workflows).
 * - **Stream mode** (`state.todoExecutionStarted`): the todo grid is replaced
 *   in-place by the live chat stream so the agent's processing is visible
 *   without leaving the onboarding shell. Once the agent finishes
 *   (`chat.isTodoExecutionDone`) a Continue button dispatches `ackTodoDemo`
 *   to advance to the workflows stage.
 */

"use client";

import { Button } from "@heroui/button";
import { Mail01Icon } from "@icons";
import * as m from "motion/react-m";
import type { Dispatch } from "react";
import { useCallback } from "react";
import { REVEAL_TODOS_INTRO } from "../../constants/messages";
import { MOTION_COMPOSER_CTA } from "../../constants/motion";
import type { UseOnboardingChatReturn } from "../../hooks/useOnboardingChat";
import type { Action, OnboardingState } from "../../state/types";
import { OnboardingCTAButton } from "../OnboardingCTAButton";
import { OnboardingTodoCards } from "../OnboardingTodoCards";
import { RevealIntroBubble } from "../RevealIntroBubble";
import { OnboardingChatStream } from "./Chat";

interface RevealTodosProps {
  state: OnboardingState;
  dispatch: Dispatch<Action>;
  /** Run-now demo chat — separate throwaway conversation, NOT the welcome
   *  conversation. See `useChatStage`. */
  chat: UseOnboardingChatReturn;
}

function generateConvoId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `onboarding-todo-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

interface SelectedTodoIndicatorProps {
  title: string;
  sourceEmail: { sender: string; subject: string } | null;
}

/** Static "selected todo" indicator rendered above the run-now demo stream.
 *  Replaces the previous chat-bubble-shaped TodoRunNowCard so the auto-sent
 *  user message never reads as a real conversation turn. */
function SelectedTodoIndicator({
  title,
  sourceEmail,
}: SelectedTodoIndicatorProps) {
  return (
    <div className="rounded-2xl bg-zinc-900 p-3">
      <div className="text-xs font-medium tracking-wide text-zinc-500 uppercase">
        Selected todo
      </div>
      <div className="mt-1 text-sm text-zinc-100">{title}</div>
      {sourceEmail && (
        <div className="mt-3 flex items-start gap-2 rounded-xl bg-zinc-800 p-3">
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
  );
}

/** Composer for the `revealTodos` stage. Renders a "Continue" CTA in the
 *  pinned footer once the run-now demo finishes — replaces the old inline
 *  button that used to sit beneath the todo result. */
export function RevealTodosComposer({
  dispatch,
  chat,
}: Pick<RevealTodosProps, "dispatch" | "chat">) {
  if (!chat.isTodoExecutionDone) return null;
  return (
    <m.div className="flex justify-center pb-2" {...MOTION_COMPOSER_CTA}>
      <OnboardingCTAButton onClick={() => dispatch({ type: "ackTodoDemo" })}>
        Continue
      </OnboardingCTAButton>
    </m.div>
  );
}

export function RevealTodos({ state, dispatch, chat }: RevealTodosProps) {
  const todos = state.server?.onboarding_todos ?? [];

  const handleExecute = useCallback(
    (todoId: string) => {
      const todo = todos.find((t) => t.id === todoId);
      if (!todo) return;
      const sourceEmail = todo.source_email ?? null;
      const emailHint = sourceEmail
        ? `\n\n[Context: derived from an email from "${sourceEmail.sender}" with subject "${sourceEmail.subject}". Reference this email and its actual contents.]`
        : "";
      const closingHint =
        "\n\n[This is an onboarding run-now demo. Execute the todo and report the result in 1-2 short sentences. Do NOT ask a follow-up question. Do NOT offer further help or automation. End on the result.]";
      const message = `Execute this todo for me: ${todo.title}${emailHint}${closingHint}`;
      dispatch({
        type: "executeTodo",
        message,
        convoId: generateConvoId(),
        todo: { id: todo.id, title: todo.title, sourceEmail },
      });
    },
    [todos, dispatch],
  );

  if (todos.length === 0) return null;

  if (state.todoExecutionStarted) {
    const selected = state.todoExecutionTodo;
    return (
      <m.div
        className="mt-10 w-full space-y-4 rounded-2xl bg-zinc-800/40 p-4 backdrop-blur-xl"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.3 }}
      >
        {selected && (
          <SelectedTodoIndicator
            title={selected.title}
            sourceEmail={selected.sourceEmail}
          />
        )}
        <OnboardingChatStream chat={chat} hideRunNowUserMessage />
      </m.div>
    );
  }

  return (
    <div className="mt-3 space-y-4">
      <RevealIntroBubble text={REVEAL_TODOS_INTRO}>
        <OnboardingTodoCards
          todos={todos.map((t) => ({
            id: t.id,
            title: t.title,
            description: t.description ?? undefined,
            source_email: t.source_email ?? undefined,
          }))}
          onExecuteTodo={handleExecute}
          isExecuting={false}
          executingTodoId={null}
          completedTodoIds={new Set()}
        />
      </RevealIntroBubble>

      <m.div
        className="flex justify-center"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 1.5, duration: 0.4 }}
      >
        <Button
          variant="light"
          size="sm"
          className="text-xs text-zinc-400 hover:text-zinc-200"
          onPress={() => dispatch({ type: "ackTodos" })}
        >
          I'll do it later
        </Button>
      </m.div>
    </div>
  );
}

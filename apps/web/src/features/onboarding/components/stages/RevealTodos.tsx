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
import * as m from "motion/react-m";
import type { Dispatch } from "react";
import { useCallback } from "react";
import {
  REVEAL_TODOS_INTRO_GMAIL,
  REVEAL_TODOS_INTRO_NO_GMAIL,
} from "../../constants/messages";
import { MOTION_COMPOSER_CTA } from "../../constants/motion";
import type { UseOnboardingChatReturn } from "../../hooks/useOnboardingChat";
import { hasGmail } from "../../state/derive";
import type { Action, OnboardingState } from "../../state/types";
import { OnboardingCTAButton } from "../OnboardingCTAButton";
import { OnboardingTodoCards } from "../OnboardingTodoCards";
import { RevealIntroBubble } from "../RevealIntroBubble";
import { OnboardingChatStream } from "./ChatStream";
import { SelectedTodoIndicator } from "./SelectedTodoIndicator";

interface RevealTodosProps {
  state: OnboardingState;
  dispatch: Dispatch<Action>;
  chat: UseOnboardingChatReturn;
}

function generateConvoId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `onboarding-todo-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

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
        className="mt-10 ml-10.75 space-y-4 rounded-2xl bg-zinc-800/40 p-4 backdrop-blur-xl"
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
        <OnboardingChatStream chat={chat} hideRunNowUserMessage hideBotAvatar />
      </m.div>
    );
  }

  const introText = hasGmail(state)
    ? REVEAL_TODOS_INTRO_GMAIL
    : REVEAL_TODOS_INTRO_NO_GMAIL;

  return (
    <div className="mt-3 space-y-4">
      <RevealIntroBubble text={introText}>
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

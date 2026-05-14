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
import { REVEAL_TODOS_INTRO } from "../../constants/messages";
import type { UseOnboardingChatReturn } from "../../hooks/useOnboardingChat";
import type { Action, OnboardingState } from "../../state/types";
import { OnboardingCTAButton } from "../OnboardingCTAButton";
import { OnboardingTodoCards } from "../OnboardingTodoCards";
import { RevealIntroBubble } from "../RevealIntroBubble";
import { OnboardingChatStream } from "./Chat";

interface RevealTodosProps {
  state: OnboardingState;
  dispatch: Dispatch<Action>;
  chat: UseOnboardingChatReturn;
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
        todo: { id: todo.id, title: todo.title, sourceEmail },
      });
    },
    [todos, dispatch],
  );

  if (todos.length === 0) return null;

  if (state.todoExecutionStarted) {
    const executingTodo = state.todoExecutionTodo
      ? todos.find((t) => t.id === state.todoExecutionTodo?.id)
      : null;
    const done = chat.isTodoExecutionDone;
    return (
      <m.div
        className="mt-10 w-full space-y-4"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.3 }}
      >
        {executingTodo && (
          <OnboardingTodoCards
            todos={[
              {
                id: executingTodo.id,
                title: executingTodo.title,
                description: executingTodo.description ?? undefined,
                source_email: executingTodo.source_email ?? undefined,
              },
            ]}
            onExecuteTodo={() => {}}
            isExecuting={!done}
            executingTodoId={done ? null : executingTodo.id}
            completedTodoIds={done ? new Set([executingTodo.id]) : new Set()}
            readOnly
          />
        )}
        <OnboardingChatStream
          chat={chat}
          todoOverride={state.todoExecutionTodo}
        />

        {chat.isTodoExecutionDone && (
          <m.div
            className="flex justify-center pt-2"
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4 }}
          >
            <OnboardingCTAButton
              onClick={() => dispatch({ type: "ackTodoDemo" })}
            >
              Continue
            </OnboardingCTAButton>
          </m.div>
        )}
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

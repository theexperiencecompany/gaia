/**
 * `revealTodos` stage. Active once `onboarding_todos` is non-empty and the
 * user hasn't acked yet. Composer-less; the user either runs a todo
 * (dispatches `executeTodo` and advances to chat) or clicks "Skip for now"
 * (dispatches `ackTodos`).
 */

"use client";

import { Button } from "@heroui/button";
import { m } from "motion/react";
import type { Dispatch } from "react";
import { useCallback } from "react";
import { REVEAL_TODOS_INTRO } from "../../constants/messages";
import type { Action, OnboardingState } from "../../state/types";
import { OnboardingTodoCards } from "../OnboardingTodoCards";
import { RevealIntroBubble } from "../RevealIntroBubble";

interface RevealTodosProps {
  state: OnboardingState;
  dispatch: Dispatch<Action>;
}

export function RevealTodos({ state, dispatch }: RevealTodosProps) {
  const todos = state.server?.onboarding_todos ?? [];

  const handleExecute = useCallback(
    (todoId: string) => {
      const todo = todos.find((t) => t.id === todoId);
      if (!todo) return;
      const message = `Execute this todo for me: ${todo.title}`;
      dispatch({ type: "executeTodo", message });
    },
    [todos, dispatch],
  );

  if (todos.length === 0) return null;

  return (
    <div className="mt-3 space-y-4">
      <RevealIntroBubble text={REVEAL_TODOS_INTRO}>
        <OnboardingTodoCards
          todos={todos.map((t) => ({ id: t.id, title: t.title }))}
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
          className="text-zinc-500"
          onPress={() => dispatch({ type: "ackTodos" })}
        >
          Skip for now
        </Button>
      </m.div>
    </div>
  );
}

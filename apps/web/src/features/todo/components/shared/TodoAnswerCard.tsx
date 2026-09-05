"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import type React from "react";
import { useState } from "react";
import { useAnswerTodo } from "@/features/todo/hooks/useAnswerTodo";
import { cn } from "@/lib/utils";

interface TodoAnswerCardProps {
  todoId: string;
  question?: string | null;
  className?: string;
}

/**
 * The decision unit for a blocked (needs_you) GAIA todo: the question and the
 * answer input in one card — the sidebar twin of the dashboard's inline
 * answer row. Answering re-queues the run.
 */
export const TodoAnswerCard: React.FC<TodoAnswerCardProps> = ({
  todoId,
  question,
  className,
}) => {
  const answerTodo = useAnswerTodo();
  const [answer, setAnswer] = useState("");

  const submit = () => {
    const trimmed = answer.trim();
    if (!trimmed) return;
    answerTodo.mutate({ todoId, answer: trimmed });
  };

  return (
    <div
      className={cn("rounded-2xl bg-zinc-800 p-4", className)}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
    >
      <p className="text-xs font-medium text-amber-400">
        GAIA is waiting on your answer to continue
      </p>
      <p className="mt-2 text-sm leading-relaxed text-zinc-200">
        {question || "GAIA needs your input to continue."}
      </p>
      <div className="mt-3 flex items-center gap-2">
        <Input
          size="sm"
          radius="lg"
          placeholder="Type your answer…"
          value={answer}
          onValueChange={setAnswer}
          onKeyDown={(e) => {
            // Don't submit while an IME composition is active (CJK users
            // press Enter to confirm candidates).
            if (e.nativeEvent.isComposing) return;
            if (e.key === "Enter") submit();
          }}
        />
        <Button
          size="sm"
          color="primary"
          radius="lg"
          isDisabled={!answer.trim()}
          isLoading={answerTodo.isPending}
          onPress={submit}
        >
          Answer
        </Button>
      </div>
    </div>
  );
};

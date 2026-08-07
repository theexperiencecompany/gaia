"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { useDisclosure } from "@heroui/modal";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import type React from "react";
import { useState } from "react";
import { StatusGlyph } from "@/components/shared/StatusGlyph";
import { ApproveConfirmModal } from "@/features/todo/components/shared/ApproveConfirmModal";
import { useAnswerTodo } from "@/features/todo/hooks/useAnswerTodo";
import { useApproveTodo } from "@/features/todo/hooks/useApproveTodo";
import { useDismissTodo } from "@/features/todo/hooks/useDismissTodo";
import type { TodayNeedsYouItem } from "@/types/features/todayTypes";
import { TODAY_QUERY_KEY } from "../../hooks/useTodayQuery";

interface NeedsYouRowProps {
  item: TodayNeedsYouItem;
}

/**
 * A proposal (Approve & send / Skip) or a blocked run: the question reads as
 * the row's subtitle, Answer reveals the inline input on demand.
 */
export const NeedsYouRow: React.FC<NeedsYouRowProps> = ({ item }) => {
  const router = useRouter();
  const queryClient = useQueryClient();
  const approveTodo = useApproveTodo();
  const dismissTodo = useDismissTodo();
  const answerTodo = useAnswerTodo();
  const [answerOpen, setAnswerOpen] = useState(false);
  const [answer, setAnswer] = useState("");
  const approveModal = useDisclosure();

  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: TODAY_QUERY_KEY });

  const confirmApprove = () =>
    approveTodo.mutate(item.todo_id, {
      onSuccess: () => {
        refresh();
        approveModal.onClose();
      },
    });

  const submitAnswer = () => {
    const trimmed = answer.trim();
    if (!trimmed) return;
    answerTodo.mutate(
      { todoId: item.todo_id, answer: trimmed },
      { onSuccess: refresh },
    );
  };

  const isBlocked = item.execution_status === "needs_you";
  const subtitle = isBlocked
    ? item.blocker_question || "GAIA needs your input to continue."
    : item.serves;

  return (
    // Row click opens the todo's full decision card in the sidebar.
    <div
      className="group cursor-pointer rounded-xl px-3 py-2 transition-colors hover:bg-zinc-900"
      onClick={() => router.push(`/todos?todoId=${item.todo_id}`)}
    >
      <div className="flex items-center gap-3">
        <StatusGlyph
          kind={isBlocked ? "blocked" : "proposed"}
          className="shrink-0"
        />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-zinc-200">
            {item.title}
          </p>
          {subtitle && (
            <p className="line-clamp-2 text-xs text-zinc-500">{subtitle}</p>
          )}
        </div>
        {!isBlocked && (
          <div
            className="flex shrink-0 items-center gap-1.5"
            onClick={(e) => e.stopPropagation()}
          >
            <Button
              size="sm"
              variant="light"
              radius="lg"
              className="text-zinc-500 opacity-0 transition-opacity group-hover:opacity-100 data-[focus-visible=true]:opacity-100"
              isLoading={dismissTodo.isPending}
              onPress={() =>
                dismissTodo.mutate(
                  { todoId: item.todo_id },
                  { onSuccess: refresh },
                )
              }
            >
              Skip
            </Button>
            <Button
              size="sm"
              color="primary"
              radius="lg"
              isLoading={approveTodo.isPending}
              onPress={approveModal.onOpen}
            >
              Approve & send
            </Button>
            <ApproveConfirmModal
              isOpen={approveModal.isOpen}
              onOpenChange={approveModal.onOpenChange}
              todoId={item.todo_id}
              onConfirm={confirmApprove}
              isConfirming={approveTodo.isPending}
            />
          </div>
        )}
        {isBlocked && !answerOpen && (
          <div onClick={(e) => e.stopPropagation()}>
            <Button
              size="sm"
              color="primary"
              variant="flat"
              radius="lg"
              className="shrink-0"
              onPress={() => setAnswerOpen(true)}
            >
              Answer
            </Button>
          </div>
        )}
      </div>
      {isBlocked && answerOpen && (
        <div
          className="mt-2 flex items-center gap-2 pl-[34px]"
          onClick={(e) => e.stopPropagation()}
        >
          <Input
            size="sm"
            radius="lg"
            autoFocus
            placeholder="Type your answer…"
            value={answer}
            onValueChange={setAnswer}
            onKeyDown={(e) => {
              if (e.key === "Enter") submitAnswer();
              if (e.key === "Escape") setAnswerOpen(false);
            }}
            className="max-w-sm"
          />
          <Button
            size="sm"
            color="primary"
            radius="lg"
            isDisabled={!answer.trim()}
            isLoading={answerTodo.isPending}
            onPress={submitAnswer}
          >
            Send
          </Button>
        </div>
      )}
    </div>
  );
};

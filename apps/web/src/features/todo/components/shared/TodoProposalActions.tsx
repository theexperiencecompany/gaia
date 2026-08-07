"use client";

import { Button } from "@heroui/button";
import { Cancel01Icon, CheckmarkCircle02Icon } from "@icons";
import type React from "react";
import { StagedDeliverablePreview } from "@/features/todo/components/shared/StagedDeliverablePreview";
import { useApproveTodo } from "@/features/todo/hooks/useApproveTodo";
import { useDismissTodo } from "@/features/todo/hooks/useDismissTodo";
import { cn } from "@/lib/utils";

interface TodoProposalActionsProps {
  todoId: string;
  /** Fallback preview text (e.g. the todo's description) shown while canvas.md loads or if it's empty. */
  fallbackPreview?: string | null;
  className?: string;
}

/**
 * The decision unit for a GAIA proposal, self-contained in one card: what
 * GAIA wants to do, the exact staged content, and the Approve/Dismiss taps.
 * State, object, and action live together so nothing needs decoding.
 */
export const TodoProposalActions: React.FC<TodoProposalActionsProps> = ({
  todoId,
  fallbackPreview,
  className,
}) => {
  const approveTodo = useApproveTodo();
  const dismissTodo = useDismissTodo();

  return (
    <div
      className={cn("rounded-2xl bg-zinc-800 p-4", className)}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
    >
      <p className="text-xs font-medium text-amber-400">
        GAIA wants to send this — approve to release it
      </p>
      <StagedDeliverablePreview
        todoId={todoId}
        fallbackPreview={fallbackPreview}
        className="mt-3"
      />
      <div className="mt-3 flex items-center gap-2">
        <Button
          size="sm"
          color="primary"
          radius="lg"
          startContent={<CheckmarkCircle02Icon className="size-4" />}
          isLoading={approveTodo.isPending}
          onPress={() => approveTodo.mutate(todoId)}
        >
          Approve & send
        </Button>
        <Button
          size="sm"
          color="default"
          variant="flat"
          radius="lg"
          startContent={<Cancel01Icon className="size-3.5" />}
          isLoading={dismissTodo.isPending}
          onPress={() => dismissTodo.mutate({ todoId })}
        >
          Dismiss
        </Button>
      </div>
    </div>
  );
};

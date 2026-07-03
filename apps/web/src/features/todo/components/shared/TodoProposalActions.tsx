"use client";

import { Button } from "@heroui/button";
import { Cancel01Icon, CheckmarkCircle02Icon } from "@icons";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import type React from "react";
import { useState } from "react";
import { ChevronDown } from "@/components/shared/icons";
import { useApproveTodo } from "@/features/todo/hooks/useApproveTodo";
import { useDismissTodo } from "@/features/todo/hooks/useDismissTodo";
import { useTodoCanvas } from "@/features/todo/hooks/useTodoCanvas";
import { cn } from "@/lib/utils";

interface TodoProposalActionsProps {
  todoId: string;
  /** Fallback preview text (e.g. the todo's description) shown while canvas.md loads or if it's empty. */
  fallbackPreview?: string | null;
  className?: string;
}

/**
 * Inline Approve/Dismiss controls for a GAIA-proposed todo, plus a
 * one-glance expandable preview of GAIA's canvas.md (falls back to the
 * todo's description) — expands in place instead of forcing a navigation.
 */
export const TodoProposalActions: React.FC<TodoProposalActionsProps> = ({
  todoId,
  fallbackPreview,
  className,
}) => {
  const [expanded, setExpanded] = useState(false);
  const approveTodo = useApproveTodo();
  const dismissTodo = useDismissTodo();
  const { content, isLoading, fetchContent } = useTodoCanvas(todoId);

  const handleToggleExpand = () => {
    setExpanded((prev) => {
      const next = !prev;
      if (next) fetchContent();
      return next;
    });
  };

  const previewText = content || fallbackPreview;

  return (
    <div className={cn("mt-2", className)} onClick={(e) => e.stopPropagation()}>
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          color="success"
          variant="flat"
          radius="lg"
          startContent={<CheckmarkCircle02Icon className="size-3.5" />}
          isLoading={approveTodo.isPending}
          onPress={() => approveTodo.mutate(todoId)}
        >
          Approve
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
        <Button
          size="sm"
          variant="light"
          radius="lg"
          isIconOnly
          aria-label={expanded ? "Collapse preview" : "Expand preview"}
          onPress={handleToggleExpand}
        >
          <ChevronDown
            className={cn(
              "size-4 transition-transform",
              expanded && "rotate-180",
            )}
          />
        </Button>
      </div>

      <AnimatePresence initial={false}>
        {expanded && (
          <m.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
            className="overflow-hidden"
          >
            <div className="mt-2 max-h-48 overflow-y-auto rounded-2xl bg-zinc-900 p-3 text-xs text-zinc-400">
              {isLoading && !previewText ? "Loading preview..." : previewText}
            </div>
          </m.div>
        )}
      </AnimatePresence>
    </div>
  );
};

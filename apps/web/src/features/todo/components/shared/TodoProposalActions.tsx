"use client";

import { Button } from "@heroui/button";
import { Spinner } from "@heroui/spinner";
import { Cancel01Icon, CheckmarkCircle02Icon } from "@icons";
import type React from "react";
import MarkdownRenderer from "@/features/chat/components/interface/MarkdownRenderer";
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
 * Drops the deliverable template's scaffolding (`# <title>` and `## Output`
 * headings) — agent bookkeeping, not content the user is approving.
 */
function stripDeliverableScaffolding(markdown: string): string {
  return markdown
    .replace(/^\s*# .*\n+/, "")
    .replace(/^\s*## Output\s*\n+/m, "")
    .trim();
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
  // The deliverable facet IS what Approve releases — never preview notes.
  const { content, isLoading } = useTodoCanvas(todoId, {
    auto: true,
    facet: "deliverable",
  });

  const previewText = content
    ? stripDeliverableScaffolding(content)
    : fallbackPreview;

  return (
    <div
      className={cn("rounded-2xl bg-zinc-800 p-4", className)}
      onClick={(e) => e.stopPropagation()}
    >
      <p className="text-xs font-medium text-amber-400">
        GAIA wants to send this — approve to release it
      </p>
      <div className="mt-3 rounded-xl bg-zinc-900 p-3">
        {isLoading && !previewText ? (
          <div className="flex justify-center py-4">
            <Spinner size="sm" color="default" />
          </div>
        ) : previewText ? (
          // Headings inside a staged draft render at card scale, not the
          // global page scale — this is a preview well, not a document.
          <div className="max-h-72 overflow-y-auto text-xs leading-relaxed text-zinc-300 [&_h1]:mt-2 [&_h1]:mb-1 [&_h1]:text-[13px] [&_h1]:font-semibold [&_h1]:first:mt-0 [&_h2]:mt-2 [&_h2]:mb-1 [&_h2]:text-[13px] [&_h2]:font-semibold [&_h2]:first:mt-0 [&_h3]:mt-2 [&_h3]:mb-1 [&_h3]:text-xs [&_h3]:font-semibold [&_h4]:text-xs [&_h4]:font-semibold [&_h5]:text-xs [&_h6]:text-xs [&_p]:my-1">
            <MarkdownRenderer content={previewText} className="text-xs" />
          </div>
        ) : (
          <p className="py-2 text-xs text-zinc-500">Nothing staged yet.</p>
        )}
      </div>
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

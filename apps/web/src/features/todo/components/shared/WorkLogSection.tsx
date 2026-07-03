"use client";

import { Spinner } from "@heroui/spinner";
import { AlertCircleIcon, CanvasIcon } from "@icons";
import type React from "react";
import MarkdownRenderer from "@/features/chat/components/interface/MarkdownRenderer";
import { useTodoCanvas } from "@/features/todo/hooks/useTodoCanvas";

interface WorkLogSectionProps {
  todoId: string;
}

/**
 * Always-visible "work log" for a GAIA-assigned todo — GAIA's canvas.md
 * rendered inline in the detail view via `useTodoCanvas`, instead of behind
 * a click-to-open modal.
 */
const WorkLogSection: React.FC<WorkLogSectionProps> = ({ todoId }) => {
  const { content, isLoading, hasError } = useTodoCanvas(todoId, {
    auto: true,
  });

  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <div className="mb-3 flex items-center gap-3">
        <div className="flex size-8 shrink-0 items-center justify-center rounded-xl bg-violet-500/15">
          <CanvasIcon className="size-4 text-violet-400" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-zinc-300">Work log</p>
          <p className="truncate text-xs text-zinc-500">
            GAIA's working memory for this task
          </p>
        </div>
        {isLoading && <Spinner size="sm" color="default" />}
      </div>

      <div className="rounded-2xl bg-zinc-900 p-3">
        {hasError ? (
          <div className="flex flex-col items-center gap-2 py-6 text-center">
            <AlertCircleIcon width={24} height={24} className="text-red-400" />
            <p className="text-xs text-zinc-400">Couldn't load the work log.</p>
          </div>
        ) : content ? (
          <MarkdownRenderer content={content} className="text-sm" />
        ) : !isLoading ? (
          <p className="py-4 text-center text-xs text-zinc-500">
            No activity yet.
          </p>
        ) : null}
      </div>
    </div>
  );
};

export default WorkLogSection;

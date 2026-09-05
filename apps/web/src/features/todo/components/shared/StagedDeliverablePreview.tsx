"use client";

import { Spinner } from "@heroui/spinner";
import type React from "react";
import MarkdownRenderer from "@/features/chat/components/interface/MarkdownRenderer";
import { useTodoCanvas } from "@/features/todo/hooks/useTodoCanvas";
import { cn } from "@/lib/utils";

interface StagedDeliverablePreviewProps {
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
 * The scrollable "well" showing the exact staged deliverable a GAIA proposal
 * will release. Loads the deliverable facet directly so the sidebar card and
 * the approve modal render one identical preview.
 */
export const StagedDeliverablePreview: React.FC<
  StagedDeliverablePreviewProps
> = ({ todoId, fallbackPreview, className }) => {
  // The deliverable facet IS what Approve releases — never preview notes.
  const { content, isLoading } = useTodoCanvas(todoId, {
    auto: true,
    facet: "deliverable",
  });

  const previewText = content
    ? stripDeliverableScaffolding(content)
    : fallbackPreview;

  return (
    <div className={cn("rounded-xl bg-zinc-900 p-3", className)}>
      {isLoading && !previewText ? (
        <div className="flex justify-center py-4">
          <Spinner size="sm" color="default" />
        </div>
      ) : previewText ? (
        // Headings inside a staged draft render at card scale, not the global
        // page scale — this is a preview well, not a document.
        <div className="max-h-72 overflow-y-auto text-xs leading-relaxed text-zinc-300 [&_h1]:mt-2 [&_h1]:mb-1 [&_h1]:text-[13px] [&_h1]:font-semibold [&_h1]:first:mt-0 [&_h2]:mt-2 [&_h2]:mb-1 [&_h2]:text-[13px] [&_h2]:font-semibold [&_h2]:first:mt-0 [&_h3]:mt-2 [&_h3]:mb-1 [&_h3]:text-xs [&_h3]:font-semibold [&_h4]:text-xs [&_h4]:font-semibold [&_h5]:text-xs [&_h6]:text-xs [&_p]:my-1">
          <MarkdownRenderer content={previewText} className="text-xs" />
        </div>
      ) : (
        <p className="py-2 text-xs text-zinc-500">Nothing staged yet.</p>
      )}
    </div>
  );
};

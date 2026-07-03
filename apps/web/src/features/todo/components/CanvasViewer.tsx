"use client";

import { Spinner } from "@heroui/spinner";
import { CanvasIcon } from "@icons";
import type React from "react";
import { useState } from "react";
import MarkdownViewerModal from "@/components/common/MarkdownViewerModal";
import { useTodoCanvas } from "@/features/todo/hooks/useTodoCanvas";

interface CanvasViewerProps {
  todoId: string;
  todoTitle: string;
}

const CanvasViewer: React.FC<CanvasViewerProps> = ({ todoId, todoTitle }) => {
  const [isOpen, setIsOpen] = useState(false);
  const { content, isLoading, hasError, fetchContent } = useTodoCanvas(todoId);

  const handleOpen = () => {
    setIsOpen(true);
    fetchContent();
  };

  return (
    <>
      <button
        type="button"
        onClick={handleOpen}
        className="flex w-full items-center gap-3 rounded-2xl bg-zinc-800 px-3 py-2.5 text-left transition-colors hover:bg-zinc-700/70"
      >
        <div className="flex size-8 shrink-0 items-center justify-center rounded-xl bg-violet-500/15">
          <CanvasIcon className="size-4 text-violet-400" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-zinc-300">canvas.md</p>
          <p className="truncate text-xs text-zinc-500">GAIA working memory</p>
        </div>
        {isLoading && <Spinner size="sm" color="default" />}
      </button>

      <MarkdownViewerModal
        isOpen={isOpen}
        onClose={() => setIsOpen(false)}
        title={`canvas.md — ${todoTitle}`}
        content={content}
        isLoading={isLoading}
        hasError={hasError}
        errorMessage="Couldn't load canvas.md. Close and reopen to try again."
      />
    </>
  );
};

export default CanvasViewer;

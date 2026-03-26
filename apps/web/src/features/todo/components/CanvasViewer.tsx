"use client";

import { Spinner } from "@heroui/spinner";
import { CanvasIcon } from "@icons";
import type React from "react";
import { useState } from "react";
import MarkdownViewerModal from "@/components/common/MarkdownViewerModal";
import { vfsApi } from "@/features/chat/api/vfsApi";

interface CanvasViewerProps {
  vfsPath: string;
  todoTitle: string;
}

const CanvasViewer: React.FC<CanvasViewerProps> = ({ vfsPath, todoTitle }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [content, setContent] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const handleOpen = async () => {
    setIsOpen(true);
    if (content !== null) return;
    setIsLoading(true);
    try {
      const res = await vfsApi.readFile(`${vfsPath}/canvas.md`);
      setContent(res.content);
    } catch {
      setContent(null);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={handleOpen}
        className="flex w-full items-center gap-3 rounded-lg border border-zinc-800 bg-zinc-900/50 px-3 py-2.5 text-left transition-colors hover:border-zinc-700 hover:bg-zinc-800/60"
      >
        <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-violet-500/15">
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
      />
    </>
  );
};

export default CanvasViewer;

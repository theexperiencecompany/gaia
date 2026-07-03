"use client";

import {
  Modal,
  ModalBody,
  ModalContent,
  ModalHeader,
  useDisclosure,
} from "@heroui/modal";
import { Spinner } from "@heroui/spinner";
import { AlertCircleIcon, CanvasIcon } from "@icons";
import type React from "react";
import MarkdownRenderer from "@/features/chat/components/interface/MarkdownRenderer";
import { useTodoCanvas } from "@/features/todo/hooks/useTodoCanvas";

interface WorkLogSectionProps {
  todoId: string;
}

/**
 * The "work log" (GAIA's canvas.md) for a GAIA-assigned todo. Rendered as a
 * compact button in the detail view; clicking opens the full log in a
 * scrollable modal via `useTodoCanvas`.
 */
const WorkLogSection: React.FC<WorkLogSectionProps> = ({ todoId }) => {
  const { isOpen, onOpen, onOpenChange } = useDisclosure();
  const { content, isLoading, hasError } = useTodoCanvas(todoId, {
    auto: isOpen,
  });

  return (
    <>
      <button
        type="button"
        onClick={onOpen}
        className="flex w-full items-center gap-3 rounded-2xl bg-zinc-800 p-4 text-left transition-colors hover:bg-zinc-700/70"
      >
        <div className="flex size-8 shrink-0 items-center justify-center rounded-xl bg-violet-500/15">
          <CanvasIcon className="size-4 text-violet-400" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-zinc-300">Work log</p>
          <p className="truncate text-xs text-zinc-500">
            GAIA's working memory for this task — tap to open
          </p>
        </div>
      </button>

      <Modal
        isOpen={isOpen}
        onOpenChange={onOpenChange}
        size="2xl"
        scrollBehavior="inside"
        classNames={{ base: "bg-zinc-900", body: "py-4" }}
      >
        <ModalContent>
          <ModalHeader className="flex items-center gap-3">
            <div className="flex size-8 shrink-0 items-center justify-center rounded-xl bg-violet-500/15">
              <CanvasIcon className="size-4 text-violet-400" />
            </div>
            <div>
              <p className="text-sm font-medium text-zinc-100">Work log</p>
              <p className="text-xs font-normal text-zinc-500">
                GAIA's working memory for this task
              </p>
            </div>
            {isLoading && <Spinner size="sm" color="default" />}
          </ModalHeader>
          <ModalBody>
            {hasError ? (
              <div className="flex flex-col items-center gap-2 py-10 text-center">
                <AlertCircleIcon
                  width={24}
                  height={24}
                  className="text-red-400"
                />
                <p className="text-xs text-zinc-400">
                  Couldn't load the work log.
                </p>
              </div>
            ) : content ? (
              <MarkdownRenderer content={content} className="text-sm" />
            ) : !isLoading ? (
              <p className="py-10 text-center text-xs text-zinc-500">
                No activity yet.
              </p>
            ) : (
              <div className="flex justify-center py-10">
                <Spinner size="sm" color="default" />
              </div>
            )}
          </ModalBody>
        </ModalContent>
      </Modal>
    </>
  );
};

export default WorkLogSection;

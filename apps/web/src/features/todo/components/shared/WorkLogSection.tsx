"use client";

import { Button } from "@heroui/button";
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
  /** A goal's canvas is its strategy doc, not a task work log — relabel it. */
  isGoal?: boolean;
}

/**
 * GAIA's canvas.md for a GAIA-assigned todo, rendered as a compact button in
 * the detail view. For a task it's the "work log" (working memory); for a goal
 * it's the "strategy" (the plan). Clicking opens the full doc in a scrollable
 * modal via `useTodoCanvas`.
 */
const WorkLogSection: React.FC<WorkLogSectionProps> = ({ todoId, isGoal }) => {
  const { isOpen, onOpen, onOpenChange } = useDisclosure();
  const { content, isLoading, hasError } = useTodoCanvas(todoId, {
    auto: isOpen,
  });

  const title = isGoal ? "Strategy" : "Work log";
  const subtitle = isGoal
    ? "GAIA's plan for this goal"
    : "GAIA's working memory for this task";
  const emptyLabel = isGoal ? "No strategy yet." : "No activity yet.";

  return (
    <>
      {/* A small real button: the one interactive row in the context block
          should look interactive, unlike the static text around it. */}
      <Button
        size="sm"
        variant="flat"
        radius="lg"
        onPress={onOpen}
        startContent={<CanvasIcon className="size-4 text-violet-400" />}
        className="text-zinc-300"
      >
        {title}
      </Button>

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
              <p className="text-sm font-medium text-zinc-100">{title}</p>
              <p className="text-xs font-normal text-zinc-500">{subtitle}</p>
            </div>
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
                  Couldn't load the {isGoal ? "strategy" : "work log"}.
                </p>
              </div>
            ) : isLoading ? (
              <div className="flex justify-center py-10">
                <Spinner size="sm" color="default" />
              </div>
            ) : content ? (
              <MarkdownRenderer content={content} className="text-sm" />
            ) : (
              <p className="py-10 text-center text-xs text-zinc-500">
                {emptyLabel}
              </p>
            )}
          </ModalBody>
        </ModalContent>
      </Modal>
    </>
  );
};

export default WorkLogSection;

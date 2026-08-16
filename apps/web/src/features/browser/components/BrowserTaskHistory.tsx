"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Modal, ModalContent } from "@heroui/modal";
import { Skeleton } from "@heroui/skeleton";
import {
  AiWebBrowsingIcon,
  AlertCircleIcon,
  CheckmarkCircle02Icon,
  Loading03Icon,
  StopCircleIcon,
} from "@icons";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { RecapSlideshow } from "@/components/browser/RecapSlideshow";
import { ChevronRight } from "@/components/shared/icons";
import { useBrowserTasks } from "../hooks/useBrowserTasks";
import type { BrowserTask } from "../types";
import { formatRelativeDate } from "../utils";

function TaskStatusBadge({ status }: { status: BrowserTask["status"] }) {
  switch (status) {
    case "completed":
      return (
        <Chip
          size="sm"
          color="success"
          variant="flat"
          radius="sm"
          startContent={<CheckmarkCircle02Icon className="h-3 w-3" />}
        >
          Done
        </Chip>
      );
    case "cancelled":
      return (
        <Chip
          size="sm"
          color="default"
          variant="flat"
          radius="sm"
          startContent={<StopCircleIcon className="h-3 w-3" />}
        >
          Stopped
        </Chip>
      );
    case "failed":
      return (
        <Chip
          size="sm"
          color="danger"
          variant="flat"
          radius="sm"
          startContent={<AlertCircleIcon className="h-3 w-3" />}
        >
          Couldn&apos;t finish
        </Chip>
      );
    case "running":
    case "paused":
      return (
        <Chip
          size="sm"
          color="primary"
          radius="sm"
          variant="flat"
          startContent={
            <div className="animate-spin">
              <Loading03Icon className="h-3 w-3" />
            </div>
          }
        >
          Working
        </Chip>
      );
  }
}

function TaskRow({ task }: { task: BrowserTask }) {
  const router = useRouter();
  const [isRecapOpen, setIsRecapOpen] = useState(false);
  const hasRecap = task.screenshots.length > 0;
  const isClickable = task.conversation_id.length > 0;

  const handleRowClick = () => {
    router.push(`/c/${task.conversation_id}`);
  };

  return (
    <>
      <div
        className={`flex items-center justify-between gap-3 rounded-2xl bg-zinc-800/50 p-3 transition-colors hover:bg-zinc-800 ${isClickable ? "cursor-pointer" : ""}`}
        onClick={isClickable ? handleRowClick : undefined}
        onKeyDown={
          isClickable
            ? (e) => {
                if (e.key === "Enter" || e.key === " ") handleRowClick();
              }
            : undefined
        }
        role={isClickable ? "button" : undefined}
        tabIndex={isClickable ? 0 : undefined}
      >
        <div className="flex min-w-0 items-center gap-3">
          {task.screenshots[0] && (
            <Image
              src={task.screenshots[0]}
              alt=""
              width={40}
              height={40}
              className="size-10 shrink-0 rounded-xl object-cover"
              unoptimized
            />
          )}
          <div className="flex min-w-0 flex-col gap-1">
            <div className="flex items-center gap-2">
              <TaskStatusBadge status={task.status} />
              {task.created_at && (
                <span className="text-xs text-zinc-500">
                  {formatRelativeDate(task.created_at)}
                </span>
              )}
            </div>
            <p className="line-clamp-2 text-sm text-zinc-300">{task.task}</p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {hasRecap && (
            <Button
              size="sm"
              variant="flat"
              onPress={() => setIsRecapOpen(true)}
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => e.stopPropagation()}
            >
              Watch recap
            </Button>
          )}
          {isClickable && <ChevronRight className="h-4 w-4 text-zinc-500" />}
        </div>
      </div>

      {hasRecap && (
        <Modal size="2xl" isOpen={isRecapOpen} onOpenChange={setIsRecapOpen}>
          <ModalContent>
            <RecapSlideshow
              shots={task.screenshots.map((url, i) => ({
                index: i + 1,
                url,
              }))}
            />
          </ModalContent>
        </Modal>
      )}
    </>
  );
}

export function BrowserTaskHistory() {
  const { tasks, isLoading, error, refetch } = useBrowserTasks();

  if (isLoading) {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-16 w-full rounded-2xl" />
        <Skeleton className="h-16 w-full rounded-2xl" />
        <Skeleton className="h-16 w-full rounded-2xl" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-2xl bg-zinc-800 p-6 text-center text-sm text-zinc-400">
        <span>Couldn&apos;t load your browser tasks.</span>
        <Button size="sm" variant="flat" onPress={() => void refetch()}>
          Retry
        </Button>
      </div>
    );
  }

  if (tasks.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 rounded-2xl bg-zinc-800 p-6 text-center">
        <div className="rounded-full bg-zinc-900 p-3">
          <AiWebBrowsingIcon className="size-5 text-zinc-500" />
        </div>
        <p className="text-sm text-zinc-400">No browser tasks yet</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {tasks.map((task) => (
        <TaskRow key={task.id} task={task} />
      ))}
    </div>
  );
}

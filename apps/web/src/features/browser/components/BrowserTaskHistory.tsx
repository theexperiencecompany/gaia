"use client";

import { Button } from "@heroui/button";
import { Modal, ModalContent } from "@heroui/modal";
import { ScrollShadow } from "@heroui/react";
import { Skeleton } from "@heroui/skeleton";
import {
  AiWebBrowsingIcon,
  Comment01Icon,
  Delete02Icon,
  PlayIcon,
} from "@icons";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { RecapSlideshow } from "@/components/browser/RecapSlideshow";
import { useBrowserTasks } from "../hooks/useBrowserTasks";
import type { BrowserTask, BrowserTaskStatus } from "../types";
import { formatRelativeDate } from "../utils";

const STATUS_META: Record<
  BrowserTaskStatus,
  { label: string; dot: string; text: string }
> = {
  completed: { label: "Done", dot: "bg-emerald-500", text: "text-emerald-400" },
  cancelled: { label: "Stopped", dot: "bg-zinc-500", text: "text-zinc-400" },
  failed: { label: "Couldn't finish", dot: "bg-red-500", text: "text-red-400" },
  running: { label: "Working", dot: "bg-[#00bbff]", text: "text-[#00bbff]" },
  paused: { label: "Working", dot: "bg-[#00bbff]", text: "text-[#00bbff]" },
};

const SOURCE_LABEL: Record<string, string> = {
  web: "Web",
  mobile: "Mobile",
  desktop: "Desktop",
  telegram: "Telegram",
  discord: "Discord",
  slack: "Slack",
  whatsapp: "WhatsApp",
  imessage: "iMessage",
};
// Sources whose conversation lives in this app, so we can deep-link to it.
const IN_APP_SOURCES = new Set(["web", "mobile", "desktop"]);

function MetaDot() {
  return <span className="size-[3px] rounded-full bg-zinc-600" />;
}

function TaskRow({
  task,
  onDelete,
  isDeleting,
}: {
  task: BrowserTask;
  onDelete: (id: string) => void;
  isDeleting: boolean;
}) {
  const router = useRouter();
  const [recapOpen, setRecapOpen] = useState(false);
  const hasRecap = task.frames.length > 0;
  const meta = STATUS_META[task.status];
  const thumb = task.frames[0]?.url;
  const sourceLabel = SOURCE_LABEL[task.source];
  const canOpenChat =
    IN_APP_SOURCES.has(task.source) && task.conversation_id.length > 0;

  return (
    <>
      <div
        className={`group flex items-center gap-3 rounded-2xl bg-zinc-800/40 p-2.5 transition-colors ${hasRecap ? "cursor-pointer hover:bg-zinc-800/80" : ""}`}
        onClick={hasRecap ? () => setRecapOpen(true) : undefined}
        onKeyDown={
          hasRecap
            ? (e) => {
                if (e.key === "Enter") setRecapOpen(true);
              }
            : undefined
        }
        role={hasRecap ? "button" : undefined}
        tabIndex={hasRecap ? 0 : undefined}
      >
        <div className="relative size-11 shrink-0 overflow-hidden rounded-lg bg-zinc-900 ring-1 ring-white/5">
          {thumb ? (
            <Image
              src={thumb}
              alt=""
              width={64}
              height={64}
              className="size-full object-cover"
              unoptimized
            />
          ) : (
            <div className="flex size-full items-center justify-center">
              <AiWebBrowsingIcon className="size-4 text-zinc-600" />
            </div>
          )}
          {hasRecap && (
            <span className="absolute inset-0 flex items-center justify-center bg-black/40 opacity-0 transition group-hover:opacity-100">
              <PlayIcon className="size-4 text-white" />
            </span>
          )}
        </div>

        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-zinc-100">
            {task.task}
          </p>
          <div className="mt-1 flex items-center gap-1.5 text-xs text-zinc-500">
            <span className={`size-1.5 rounded-full ${meta.dot}`} />
            <span className={meta.text}>{meta.label}</span>
            {task.created_at && (
              <>
                <MetaDot />
                <span>{formatRelativeDate(task.created_at)}</span>
              </>
            )}
            {task.steps > 0 && (
              <>
                <MetaDot />
                <span>
                  {task.steps} {task.steps === 1 ? "step" : "steps"}
                </span>
              </>
            )}
            {sourceLabel && (
              <>
                <MetaDot />
                <span>{sourceLabel}</span>
              </>
            )}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
          {canOpenChat && (
            <Button
              isIconOnly
              size="sm"
              variant="light"
              radius="full"
              className="text-zinc-400"
              aria-label="Open conversation"
              onPress={() => router.push(`/c/${task.conversation_id}`)}
            >
              <Comment01Icon className="size-4" />
            </Button>
          )}
          <Button
            isIconOnly
            size="sm"
            variant="light"
            color="danger"
            radius="full"
            aria-label="Delete task"
            isLoading={isDeleting}
            onPress={() => onDelete(task.id)}
          >
            {!isDeleting && <Delete02Icon className="size-4" />}
          </Button>
        </div>
      </div>

      {hasRecap && (
        <Modal size="2xl" isOpen={recapOpen} onOpenChange={setRecapOpen}>
          <ModalContent>
            <RecapSlideshow
              title={task.task}
              enableKeyboard
              shots={task.frames.map((f, i) => ({
                index: i + 1,
                url: f.url,
                caption: f.caption,
              }))}
            />
          </ModalContent>
        </Modal>
      )}
    </>
  );
}

export function BrowserTaskHistory() {
  const { tasks, isLoading, error, refetch, deleteTask, deletingId } =
    useBrowserTasks();

  return (
    <section>
      <h3 className="mb-3 text-sm font-semibold text-zinc-200">Task history</h3>

      {isLoading ? (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-16 w-full rounded-2xl" />
          <Skeleton className="h-16 w-full rounded-2xl" />
          <Skeleton className="h-16 w-full rounded-2xl" />
        </div>
      ) : error ? (
        <div className="flex flex-col items-center gap-3 rounded-2xl bg-zinc-800/40 p-6 text-center text-sm text-zinc-400">
          <span>Couldn&apos;t load your browser tasks.</span>
          <Button size="sm" variant="flat" onPress={() => void refetch()}>
            Retry
          </Button>
        </div>
      ) : tasks.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-3 rounded-2xl bg-zinc-800/40 p-8 text-center">
          <div className="rounded-full bg-zinc-900 p-3">
            <AiWebBrowsingIcon className="size-5 text-zinc-500" />
          </div>
          <p className="text-sm text-zinc-400">No browser tasks yet</p>
          <p className="max-w-xs text-xs text-zinc-500">
            Ask GAIA to do something on the web and it will show up here with a
            replayable recap.
          </p>
        </div>
      ) : (
        <ScrollShadow className="max-h-[540px]">
          <div className="flex flex-col gap-2 pr-1">
            {tasks.map((task) => (
              <TaskRow
                key={task.id}
                task={task}
                onDelete={deleteTask}
                isDeleting={deletingId === task.id}
              />
            ))}
          </div>
        </ScrollShadow>
      )}
    </section>
  );
}

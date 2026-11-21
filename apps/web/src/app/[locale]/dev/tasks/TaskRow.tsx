"use client";

import { Button } from "@heroui/button";
import { Checkbox } from "@heroui/checkbox";
import {
  BubbleChatIcon,
  CheckListIcon,
  CheckmarkCircle02Icon,
  Flag02Icon,
  Link01Icon,
} from "@icons";

import { cn } from "@/lib/utils";
import type { Priority } from "@/types/features/todoTypes";
import {
  AppIcon,
  type ChipTone,
  IntegrationStack,
  MetaChip,
  TaskIconTile,
  WHEN_ICONS,
} from "./TaskParts";
import type { Task } from "./taskModel";

interface TaskRowProps {
  task: Task;
  onToggleDone: (task: Task) => void;
  onOpen: (task: Task) => void;
  /** The task shown in the sidebar. */
  isSelected?: boolean;
  /** How many of the steps inside this task are done; the steps show when it is opened. */
  steps?: { done: number; total: number };
  /** Shown when a step surfaces outside its task, as in Needs you. */
  parentTitle?: string;
}

/** The todo list's priority language: the checkbox ring and the tag share one colour. */
const PRIORITY_RING: Record<Priority, string> = {
  high: "before:border-red-500",
  medium: "before:border-yellow-500",
  low: "before:border-blue-500",
  none: "before:border-zinc-600",
};

const PRIORITY_TAG: Record<
  Exclude<Priority, "none">,
  { label: string; tone: ChipTone }
> = {
  high: { label: "High", tone: "danger" },
  medium: { label: "Medium", tone: "warning" },
  low: { label: "Low", tone: "info" },
};

/** What GAIA is waiting on, as an icon and two words; the detail is inside the task. */
const ASK_NEED = {
  approval: { label: "Needs approval", Icon: CheckmarkCircle02Icon },
  question: { label: "Has a question", Icon: BubbleChatIcon },
  reconnect: { label: "Needs reconnecting", Icon: Link01Icon },
} as const;

function AskChip({ kind }: { kind: keyof typeof ASK_NEED }) {
  const { label, Icon } = ASK_NEED[kind];
  return (
    <MetaChip tone="warning" icon={<Icon className="size-3.5" />}>
      {label}
    </MetaChip>
  );
}

/** The one rule for the leading mark: you get a checkbox, GAIA gets a tile. */
function Leading({ task, onToggleDone }: TaskRowProps) {
  if (task.assignee === "gaia")
    return <TaskIconTile icon={task.icon} size={28} />;
  const isDone = task.state === "done";
  return (
    <Checkbox
      aria-label={isDone ? `Reopen ${task.title}` : `Complete ${task.title}`}
      radius="full"
      isSelected={isDone}
      onValueChange={() => onToggleDone(task)}
      classNames={{
        base: "pointer-events-auto m-0 p-0",
        wrapper: cn(
          "m-0 size-5 before:border-2 after:bg-zinc-300",
          PRIORITY_RING[task.priority],
        ),
        icon: "text-zinc-900",
      }}
    />
  );
}

/**
 * When a task is due or runs, always as one chip. Colour is kept for the two that
 * need you today; an event trigger leads with the app that fires it.
 */
function When({ task }: { task: Task }) {
  const { when } = task;
  // A workflow that is switched off has no next run to show.
  if (task.state === "paused") return <MetaChip>Disabled</MetaChip>;
  if (!when.label) return null;
  const Icon = WHEN_ICONS[when.kind];
  const tone: ChipTone = when.overdue
    ? "danger"
    : when.isToday
      ? "success"
      : when.kind === "schedule"
        ? "info"
        : "default";

  return (
    <MetaChip
      tone={tone}
      icon={
        when.app ? (
          <AppIcon id={when.app} size={14} />
        ) : (
          <Icon className="size-3.5" />
        )
      }
    >
      {when.overdue ? `Overdue, ${when.label}` : when.label}
    </MetaChip>
  );
}

export default function TaskRow(props: TaskRowProps) {
  const { task, steps, parentTitle, onOpen, isSelected } = props;
  const isDone = task.state === "done";
  const priority =
    task.priority === "none" ? null : PRIORITY_TAG[task.priority];

  return (
    <li className="relative">
      <Button
        aria-label={`Open ${task.title}`}
        variant="light"
        disableRipple
        onPress={() => onOpen(task)}
        className={cn(
          "absolute inset-0 h-full w-full min-w-0 rounded-xl p-0 data-[hover=true]:bg-white/[0.04] data-[pressed=true]:scale-100",
          isSelected && "bg-white/[0.06]",
        )}
      />
      <div
        className={cn(
          "pointer-events-none relative flex gap-3.5 px-2 py-2",
          (isDone || (task.state === "paused" && !task.ask)) && "opacity-45",
        )}
      >
        <span className="flex size-7 shrink-0 -translate-y-0.5 items-center justify-center">
          <Leading {...props} />
        </span>

        <div className="flex min-h-7 min-w-0 flex-1 items-center gap-2">
          <p
            className={cn(
              "truncate text-[15px] leading-6",
              isDone
                ? "text-zinc-400 line-through decoration-zinc-600"
                : "text-zinc-100",
            )}
          >
            {task.title}
          </p>
          {parentTitle && (
            <span className="shrink-0 text-[13px] text-zinc-500">
              in {parentTitle}
            </span>
          )}
          {!isDone && (
            <>
              {priority && (
                <MetaChip
                  tone={priority.tone}
                  icon={<Flag02Icon className="size-3.5" />}
                >
                  {priority.label}
                </MetaChip>
              )}
              {steps && (
                <MetaChip icon={<CheckListIcon className="size-3.5" />}>
                  {steps.done}/{steps.total}
                </MetaChip>
              )}
              {task.assignee === "gaia" && (
                <IntegrationStack ids={task.integrations} size={15} />
              )}
            </>
          )}
        </div>

        {!isDone && (
          <span className="flex h-7 shrink-0 items-center">
            {task.ask ? <AskChip kind={task.ask.kind} /> : <When task={task} />}
          </span>
        )}
      </div>
    </li>
  );
}

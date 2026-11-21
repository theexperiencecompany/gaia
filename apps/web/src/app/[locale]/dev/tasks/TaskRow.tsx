"use client";

import { CheckListIcon, Flag02Icon } from "@icons";

import { GaiaButton } from "@/components/shared/GaiaButton";
import { cn } from "@/lib/utils";
import type { Priority } from "@/types/features/todoTypes";
import { AppIcon, IntegrationStack } from "./AppIcon";
import { type ChipTone, MetaChip } from "./MetaChip";
import TaskCheckbox from "./TaskCheckbox";
import { TaskIconTile } from "./TaskIconTile";
import { NEEDS, WHEN_ICONS } from "./taskIcons";
import { isRepeating, type Need, needOf, type Task } from "./taskModel";

interface TaskRowProps {
  task: Task;
  onToggleDone: (task: Task) => void;
  onOpen: (task: Task) => void;
  /** The task shown in the sidebar. */
  isSelected?: boolean;
  /** How many of the subtasks inside this task are done; they show when it is opened. */
  subtasks?: { done: number; total: number };
  /** Shown when a subtask surfaces outside its task, as in Needs you. */
  parentTitle?: string;
}

const PRIORITY_TAG: Record<
  Exclude<Priority, "none">,
  { label: string; tone: ChipTone }
> = {
  high: { label: "High", tone: "danger" },
  medium: { label: "Medium", tone: "warning" },
  low: { label: "Low", tone: "info" },
};

function NeedChip({ need }: { need: Need }) {
  const { label, Icon } = NEEDS[need];
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
    <TaskCheckbox
      label={isDone ? `Reopen ${task.title}` : `Complete ${task.title}`}
      isSelected={isDone}
      onChange={() => onToggleDone(task)}
      priority={task.priority}
      className="pointer-events-auto"
    />
  );
}

/**
 * When a task is due or runs, always as one chip. Colour is kept for the two that
 * need you today; an event trigger leads with the app that fires it.
 */
function When({ task }: { task: Task }) {
  const { when } = task;
  // A task that is switched off has no next run to show.
  if (task.state === "paused")
    return <MetaChip>{isRepeating(when) ? "Disabled" : "Stopped"}</MetaChip>;
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
  const { task, subtasks, parentTitle, onOpen, isSelected } = props;
  const isDone = task.state === "done";
  const need = needOf(task);
  const priority =
    task.priority === "none" ? null : PRIORITY_TAG[task.priority];

  return (
    <li className="relative">
      <GaiaButton
        aria-label={`Open ${task.title}`}
        aria-current={isSelected || undefined}
        variant="row"
        shape="md"
        inset="none"
        onPress={() => onOpen(task)}
        className="absolute inset-0 h-full w-full min-w-0"
      />
      <div
        className={cn(
          "pointer-events-none relative flex gap-3.5 px-2 py-2",
          (isDone || (task.state === "paused" && !need)) && "opacity-45",
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
              {subtasks && (
                <MetaChip icon={<CheckListIcon className="size-3.5" />}>
                  {subtasks.done}/{subtasks.total}
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
            {need ? <NeedChip need={need} /> : <When task={task} />}
          </span>
        )}
      </div>
    </li>
  );
}

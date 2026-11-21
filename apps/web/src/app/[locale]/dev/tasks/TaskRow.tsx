"use client";

import {
  BubbleChatIcon,
  CheckListIcon,
  CheckmarkCircle02Icon,
  Flag02Icon,
  Link01Icon,
} from "@icons";

import { GaiaButton } from "@/components/shared/GaiaButton";
import { cn } from "@/lib/utils";
import type { Priority } from "@/types/features/todoTypes";
import TaskCheckbox from "./TaskCheckbox";
import {
  type ChipTone,
  IntegrationStack,
  MetaChip,
  TaskIconTile,
  WhenChip,
} from "./TaskParts";
import type { Task } from "./taskModel";

interface TaskRowProps {
  task: Task;
  onToggleDone: (task: Task) => void;
  onOpen: (task: Task) => void;
  /** The task shown in the sidebar. */
  isSelected?: boolean;
  /** How many of the subtasks inside this task are done; they show when it is opened. */
  steps?: { done: number; total: number };
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

/** What GAIA is waiting on, as an icon and two words; the detail is inside the task. */
const ASK_NEED = {
  approval: { label: "Needs approval", Icon: CheckmarkCircle02Icon },
  question: { label: "Has a question", Icon: BubbleChatIcon },
  reconnect: { label: "Needs reconnecting", Icon: Link01Icon },
  connect: { label: "Needs an app", Icon: Link01Icon },
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
    <TaskCheckbox
      label={isDone ? `Reopen ${task.title}` : `Complete ${task.title}`}
      isSelected={isDone}
      onChange={() => onToggleDone(task)}
      priority={task.priority}
      className="pointer-events-auto"
    />
  );
}

function When({ task }: { task: Task }) {
  // A workflow that is switched off has no next run to show.
  if (task.state === "paused") return <MetaChip>Disabled</MetaChip>;
  return <WhenChip when={task.when} />;
}

export default function TaskRow(props: TaskRowProps) {
  const { task, steps, parentTitle, onOpen, isSelected } = props;
  const isDone = task.state === "done";
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

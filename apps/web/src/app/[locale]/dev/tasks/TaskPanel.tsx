"use client";

import { Button } from "@heroui/button";
import { Checkbox } from "@heroui/checkbox";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/dropdown";
import { Textarea } from "@heroui/input";
import {
  Comment01Icon,
  Delete02Icon,
  MoreHorizontalIcon,
  PauseIcon,
  PlayIcon,
  Share01Icon,
} from "@icons";
import type { ComponentType } from "react";

import type { Workflow } from "@/features/workflows/api/workflowApi";
import { cn } from "@/lib/utils";
import TaskAsk, { type AskAnswer } from "./TaskAsk";
import TaskIcon from "./TaskIcon";
import TaskProperties from "./TaskProperties";
import TaskRecord from "./TaskRecord";
import TaskSteps from "./TaskSteps";
import { isRepeating, type Task } from "./taskModel";

interface TaskPanelProps {
  task: Task;
  /** workflow.steps, for a task GAIA runs again and again. */
  steps?: Workflow["steps"];
  onChange: (task: Task) => void;
  onAnswer: (task: Task, answer: AskAnswer) => void;
  onDelete: (task: Task) => void;
}

/** Borderless field: reads as text and stays exactly where it is when you click into it. */
const BARE =
  "h-auto min-h-0 border-none bg-transparent px-0 py-0 shadow-none data-[hover=true]:bg-transparent group-data-[focus=true]:bg-transparent group-data-[focus-visible=true]:ring-0 group-data-[focus-visible=true]:ring-offset-0";

export { BARE as BARE_FIELD };

const PRIORITY_RING = {
  high: "before:border-red-500",
  medium: "before:border-yellow-500",
  low: "before:border-blue-500",
  none: "before:border-zinc-600",
} as const;

interface MenuAction {
  key: string;
  label: string;
  Icon: ComponentType<{ className?: string }>;
  isDanger?: boolean;
  onPress?: () => void;
}

/**
 * Every task in the sidebar, the same way: its name, what it is, when, and the
 * rest. Yours leads with a checkbox; GAIA's leads with its icon and keeps a record.
 */
export default function TaskPanel({
  task,
  steps,
  onChange,
  onAnswer,
  onDelete,
}: TaskPanelProps) {
  const isYours = task.assignee === "you";
  const isDone = task.state === "done";
  const isOff = task.state === "paused";
  const repeats = isRepeating(task.when);
  const update = (patch: Partial<Task>) => onChange({ ...task, ...patch });

  const title = (
    <Textarea
      aria-label="Title"
      value={task.title}
      onValueChange={(next) => update({ title: next })}
      minRows={1}
      variant="flat"
      classNames={{
        base: "min-w-0 flex-1",
        input: cn(
          "resize-none text-2xl font-medium leading-8",
          isDone
            ? "!text-zinc-500 line-through decoration-zinc-600"
            : "!text-zinc-100",
        ),
        inputWrapper: BARE,
      }}
    />
  );

  const menu: MenuAction[] = [
    ...(isYours
      ? []
      : [{ key: "chat", label: "Open chat", Icon: Comment01Icon }]),
    ...(repeats && !task.ask
      ? [
          isOff
            ? {
                key: "enable",
                label: "Enable",
                Icon: PlayIcon,
                onPress: () => update({ state: "standing" }),
              }
            : {
                key: "disable",
                label: "Disable",
                Icon: PauseIcon,
                onPress: () => update({ state: "paused" }),
              },
          {
            key: "publish",
            label: "Publish to the community",
            Icon: Share01Icon,
          },
        ]
      : []),
    {
      key: "delete",
      label: "Delete",
      Icon: Delete02Icon,
      isDanger: true,
      onPress: () => onDelete(task),
    },
  ];

  const runNow = () =>
    update({
      runs: [
        {
          id: crypto.randomUUID(),
          at: "Just now",
          outcome: "success",
          summary: "Started by you",
          duration: "1s",
        },
        ...task.runs,
      ],
    });

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 space-y-5 overflow-y-auto px-6 pb-6 pt-2">
        <div className="space-y-2.5">
          {isYours ? (
            <div className="flex items-start gap-3">
              <span className="flex h-8 shrink-0 items-center">
                <Checkbox
                  aria-label={isDone ? "Reopen" : "Mark done"}
                  radius="full"
                  isSelected={isDone}
                  onValueChange={(done) =>
                    update({ state: done ? "done" : "open", doneToday: done })
                  }
                  classNames={{
                    base: "m-0 p-0",
                    wrapper: cn(
                      "m-0 size-5 before:border-2 after:bg-zinc-300",
                      PRIORITY_RING[task.priority],
                    ),
                    icon: "text-zinc-900",
                  }}
                />
              </span>
              {title}
            </div>
          ) : (
            <div className="space-y-3">
              <TaskIcon
                icon={task.icon}
                onChange={(icon) => update({ icon })}
              />
              {title}
            </div>
          )}
          {/* One body under the name: your notes on a to-do, the brief on GAIA's task. */}
          <Textarea
            aria-label={isYours ? "Description" : "What GAIA should do"}
            value={(isYours ? task.description : task.instructions) ?? ""}
            onValueChange={(text) =>
              update(isYours ? { description: text } : { instructions: text })
            }
            placeholder={isYours ? "Add a description" : "What should GAIA do?"}
            minRows={1}
            variant="flat"
            classNames={{
              input:
                "resize-none text-sm leading-relaxed !text-zinc-400 placeholder:text-zinc-600",
              inputWrapper: BARE,
            }}
          />
        </div>

        {isOff && !task.ask && (
          <div className="flex items-center justify-between gap-3 rounded-2xl bg-zinc-800 py-2.5 pl-4 pr-2.5">
            <p className="text-sm text-zinc-300">Disabled, so it won't run.</p>
            <Button
              size="sm"
              variant="flat"
              className="bg-zinc-700 text-zinc-100"
              onPress={() => update({ state: "standing" })}
            >
              Enable
            </Button>
          </div>
        )}

        {!isDone && (
          <TaskAsk task={task} onAnswer={(answer) => onAnswer(task, answer)} />
        )}

        <TaskProperties task={task} update={update} />

        {!repeats && <TaskSteps task={task} update={update} />}

        {!isYours && <TaskRecord task={task} steps={steps} />}
      </div>

      <div className="flex items-center gap-2 p-3">
        {!isYours &&
          (repeats ? (
            !isOff && (
              <Button
                size="sm"
                variant="flat"
                startContent={<PlayIcon className="size-4" />}
                onPress={runNow}
              >
                Run now
              </Button>
            )
          ) : (
            <Button
              size="sm"
              variant="flat"
              startContent={<Comment01Icon className="size-4" />}
            >
              Open chat
            </Button>
          ))}
        <Dropdown placement="top-end">
          <DropdownTrigger>
            <Button
              isIconOnly
              size="sm"
              variant="light"
              aria-label="More"
              className="ml-auto text-zinc-400"
            >
              <MoreHorizontalIcon className="size-4" />
            </Button>
          </DropdownTrigger>
          <DropdownMenu
            aria-label="Task actions"
            items={menu.filter((action) => action.key !== "chat" || repeats)}
          >
            {(action) => (
              <DropdownItem
                key={action.key}
                color={action.isDanger ? "danger" : "default"}
                className={action.isDanger ? "text-danger" : undefined}
                startContent={<action.Icon className="size-4" />}
                onPress={action.onPress}
              >
                {action.label}
              </DropdownItem>
            )}
          </DropdownMenu>
        </Dropdown>
      </div>
    </div>
  );
}

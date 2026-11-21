"use client";

import { Dropdown, TextArea } from "@heroui/react";
import {
  Comment01Icon,
  Delete02Icon,
  MoreHorizontalIcon,
  PauseIcon,
  PlayIcon,
  Share01Icon,
} from "@icons";
import type { ComponentType } from "react";

import { inputVariants } from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { shapeVariants } from "@/components/shared/shape";
import { toneVariants } from "@/components/shared/tone";
import type { Workflow } from "@/features/workflows/api/workflowApi";
import { cn } from "@/lib/utils";
import TaskAsk, { type AskAnswer } from "./TaskAsk";
import TaskCheckbox from "./TaskCheckbox";
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
  /** Whether a copy of this task is on Explore as a template. */
  isPublished?: boolean;
  onPublishToggle?: () => void;
}

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
  isPublished = false,
  onPublishToggle,
}: TaskPanelProps) {
  const isYours = task.assignee === "you";
  const isDone = task.state === "done";
  const isOff = task.state === "paused";
  const repeats = isRepeating(task.when);
  const update = (patch: Partial<Task>) => onChange({ ...task, ...patch });

  const title = (
    <TextArea
      aria-label="Title"
      value={task.title}
      onChange={(event) => update({ title: event.target.value })}
      rows={1}
      className={inputVariants({
        variant: "inline",
        className: toneVariants({
          tone: isDone ? "faint" : "strong",
          className: cn(
            "field-sizing-content block w-full min-w-0 flex-1 resize-none text-2xl leading-8 font-medium",
            isDone && "line-through decoration-zinc-600",
          ),
        }),
      })}
    />
  );

  // A one-off GAIA task opens its chat from the footer, so only a repeating one lists it here.
  const menu: MenuAction[] = [
    ...(repeats && !isYours
      ? [{ key: "chat", label: "Open chat", Icon: Comment01Icon }]
      : []),
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
            label: isPublished ? "Unpublish" : "Publish to the community",
            Icon: Share01Icon,
            onPress: onPublishToggle,
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
      <div className="flex-1 space-y-5 overflow-y-auto px-6 pt-2 pb-6">
        <div className="space-y-2.5">
          {isYours ? (
            <div className="flex items-start gap-3">
              <span className="flex h-8 shrink-0 items-center">
                <TaskCheckbox
                  label={isDone ? "Reopen" : "Mark done"}
                  isSelected={isDone}
                  priority={task.priority}
                  onChange={(done) =>
                    update({ state: done ? "done" : "open", doneToday: done })
                  }
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
          <TextArea
            aria-label={isYours ? "Description" : "What GAIA should do"}
            value={(isYours ? task.description : task.instructions) ?? ""}
            onChange={(event) =>
              update(
                isYours
                  ? { description: event.target.value }
                  : { instructions: event.target.value },
              )
            }
            placeholder={isYours ? "Add a description" : "What should GAIA do?"}
            rows={1}
            className={inputVariants({
              variant: "inline",
              placeholder: "subtle",
              className: toneVariants({
                tone: "muted",
                className:
                  "field-sizing-content block w-full resize-none text-sm leading-relaxed",
              }),
            })}
          />
        </div>

        {isOff && !task.ask && (
          <div className="flex items-center justify-between gap-3 rounded-2xl bg-zinc-800 py-2.5 pr-2.5 pl-4">
            <p className="text-sm text-zinc-300">Disabled, so it won't run.</p>
            <GaiaButton
              size="sm"
              variant="default-solid"
              tone="strong"
              onPress={() => update({ state: "standing" })}
            >
              Enable
            </GaiaButton>
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
              <GaiaButton size="sm" variant="default-soft" onPress={runNow}>
                <PlayIcon className="size-4" />
                Run now
              </GaiaButton>
            )
          ) : (
            <GaiaButton size="sm" variant="default-soft">
              <Comment01Icon className="size-4" />
              Open chat
            </GaiaButton>
          ))}
        <Dropdown>
          <GaiaButton
            isIconOnly
            size="sm"
            variant="quiet"
            tone="muted"
            aria-label="More"
            className="ml-auto"
          >
            <MoreHorizontalIcon className="size-4" />
          </GaiaButton>
          <Dropdown.Popover
            placement="top end"
            offset={7}
            className={shapeVariants({ shape: "lg" })}
          >
            <Dropdown.Menu aria-label="Task actions">
              {menu.map((action) => (
                <Dropdown.Item
                  key={action.key}
                  id={action.key}
                  textValue={action.label}
                  variant={action.isDanger ? "danger" : "default"}
                  onAction={action.onPress}
                  className="gap-2"
                >
                  <action.Icon className="size-4" />
                  {action.label}
                </Dropdown.Item>
              ))}
            </Dropdown.Menu>
          </Dropdown.Popover>
        </Dropdown>
      </div>
    </div>
  );
}

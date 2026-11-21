"use client";

import { Popover, Switch } from "@heroui/react";
import { Flag02Icon, Tick02Icon } from "@icons";
import { type ReactNode, useState } from "react";

import { switchVariants } from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { shapeVariants } from "@/components/shared/shape";
import { cn } from "@/lib/utils";
import type { Priority } from "@/types/features/todoTypes";
import { AppIcon } from "./AppIcon";
import { APP_NAMES } from "./demoTriggers";
import { PropertyRow } from "./PropertyRow";
import { statusLine } from "./statusModel";
import TaskApps from "./TaskApps";
import { TaskIconTile } from "./TaskIconTile";
import { isRepeating, type Task } from "./taskModel";
import WhenField from "./WhenField";
import { ago } from "./watchModel";

type Update = (patch: Partial<Task>) => void;

const notifySwitch = switchVariants();

const PRIORITY: { key: Priority; label: string; color: string }[] = [
  { key: "high", label: "High", color: "text-red-500" },
  { key: "medium", label: "Medium", color: "text-yellow-500" },
  { key: "low", label: "Low", color: "text-blue-500" },
  { key: "none", label: "None", color: "text-zinc-600" },
];

function PriorityRow({ task, update }: { task: Task; update: Update }) {
  const [isOpen, setIsOpen] = useState(false);
  const current = PRIORITY.find((item) => item.key === task.priority);
  return (
    <PropertyRow label="Priority">
      <Popover isOpen={isOpen} onOpenChange={setIsOpen}>
        <GaiaButton
          size="sm"
          variant="property"
          tone={task.priority === "none" ? "faint" : "bright"}
          inset="tight"
          aria-label="Priority"
          className="-ml-2 h-8 min-w-0 flex-1 justify-start gap-1.5 text-sm"
        >
          <Flag02Icon className={cn("size-4", current?.color)} />
          {current?.label}
        </GaiaButton>
        <Popover.Content
          placement="bottom start"
          offset={6}
          className={shapeVariants({
            shape: "md",
            className: "w-44 outline-none",
          })}
        >
          <div className="w-full p-1">
            {PRIORITY.map((item) => (
              <GaiaButton
                key={item.key}
                size="sm"
                variant="property"
                tone="bright"
                inset="tight"
                onPress={() => {
                  update({ priority: item.key });
                  setIsOpen(false);
                }}
                className="h-8 w-full justify-start gap-2 text-sm"
              >
                <Flag02Icon className={cn("size-4", item.color)} />
                {item.label}
                {item.key === task.priority && (
                  <Tick02Icon className="ml-auto size-4 text-zinc-400" />
                )}
              </GaiaButton>
            ))}
          </div>
        </Popover.Content>
      </Popover>
    </PropertyRow>
  );
}

/** A plain value that is read, not edited: one or two lines on the row. */
function ReadRow({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <PropertyRow label={label} hint={hint}>
      <span className="flex min-w-0 items-start gap-1.5 py-2 text-sm leading-5 text-zinc-200">
        {children}
      </span>
    </PropertyRow>
  );
}

/** The facts about a task, one per row; click a value to change it. */
export default function TaskProperties({
  task,
  update,
  parent,
  onOpen,
  isWhenOpen,
  onWhenOpenChange,
}: {
  task: Task;
  update: Update;
  /** The task this one is a subtask of. */
  parent?: Task;
  onOpen: (task: Task) => void;
  /** Whether the When editor is open, so the panel can open it from a watch's fix. */
  isWhenOpen: boolean;
  onWhenOpenChange: (isOpen: boolean) => void;
}) {
  const isYours = task.assignee === "you";
  const notifyLabel = isYours ? "Nudges" : "Notify me";
  // A stopped task says so above its properties, and a question says it in the ask.
  const status =
    !isYours && !isRepeating(task.when) && task.state !== "paused"
      ? statusLine(task)
      : undefined;
  const lastReceived = task.when.webhook?.lastReceived;
  return (
    <div>
      {task.origin && (
        <ReadRow label="Set up by" hint={task.origin.why}>
          <span className="flex h-5 shrink-0 items-center">
            <AppIcon id={task.origin.app} size={15} />
          </span>
          {/* "Calendar", not "Google Calendar": the logo already says whose it is. */}
          GAIA, from{" "}
          {(APP_NAMES[task.origin.app] ?? task.origin.app).replace(
            /^Google /,
            "",
          )}
        </ReadRow>
      )}
      {parent && (
        <PropertyRow label="Part of">
          <GaiaButton
            size="sm"
            variant="property"
            tone="bright"
            inset="tight"
            onPress={() => onOpen(parent)}
            className="-ml-2 h-8 min-w-0 gap-2 text-sm"
          >
            {parent.assignee === "gaia" && (
              <TaskIconTile icon={parent.icon} size={18} />
            )}
            <span className="truncate">{parent.title}</span>
          </GaiaButton>
        </PropertyRow>
      )}
      {status && (
        <ReadRow label="Status">
          <span className="line-clamp-3">{status}</span>
        </ReadRow>
      )}
      <WhenField
        when={task.when}
        onChange={(when) => update({ when })}
        forGaia={!isYours}
        runCount={task.runCount}
        isOpen={isWhenOpen}
        onOpenChange={onWhenOpenChange}
      />
      {lastReceived && (
        <ReadRow label="Last received">{ago(lastReceived)}</ReadRow>
      )}
      {!isRepeating(task.when) && <PriorityRow task={task} update={update} />}
      {!isYours && <TaskApps task={task} update={update} />}
      <PropertyRow
        label={notifyLabel}
        hint={
          isYours
            ? "GAIA reminds you before this is due: in the app, and on Telegram, WhatsApp or wherever you talk to it."
            : "GAIA tells you when this finishes: in the app, and on Telegram, WhatsApp or wherever you talk to it."
        }
      >
        <Switch
          aria-label={notifyLabel}
          isSelected={task.notify}
          onChange={(notify) => update({ notify })}
        >
          <Switch.Control className={notifySwitch.control()}>
            <Switch.Thumb className={notifySwitch.thumb()} />
          </Switch.Control>
        </Switch>
      </PropertyRow>
      {task.source && (
        <PropertyRow label="From">
          <GaiaButton
            size="sm"
            variant="property"
            tone="bright"
            inset="tight"
            className="-ml-2 h-8 min-w-0 gap-1.5 text-sm"
          >
            <AppIcon id={task.source.app} size={15} />
            Open email
          </GaiaButton>
        </PropertyRow>
      )}
    </div>
  );
}

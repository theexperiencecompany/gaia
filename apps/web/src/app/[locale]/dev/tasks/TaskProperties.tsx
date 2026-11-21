"use client";

import { Popover, Switch } from "@heroui/react";
import { Flag02Icon, Tick02Icon } from "@icons";
import { useState } from "react";

import { switchVariants } from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { shapeVariants } from "@/components/shared/shape";
import { cn } from "@/lib/utils";
import type { Priority } from "@/types/features/todoTypes";
import { AppIcon } from "./AppIcons";
import { PropertyRow } from "./PropertyRow";
import { isRepeating, type Task } from "./taskModel";
import WhenField from "./WhenField";

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

/** The facts about a task, one per row; click a value to change it. */
export default function TaskProperties({
  task,
  update,
}: {
  task: Task;
  update: Update;
}) {
  const isYours = task.assignee === "you";
  const notifyLabel = isYours ? "Nudges" : "Notify me";
  return (
    <div>
      {!isYours && task.status && !isRepeating(task.when) && (
        <PropertyRow label="Status">
          <span className="line-clamp-2 py-1.5 text-sm leading-5 text-zinc-200">
            {task.status}
          </span>
        </PropertyRow>
      )}
      <WhenField
        when={task.when}
        onChange={(when) => update({ when })}
        forGaia={!isYours}
      />
      {!isRepeating(task.when) && <PriorityRow task={task} update={update} />}
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

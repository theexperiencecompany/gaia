"use client";

import { Button } from "@heroui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@heroui/popover";
import { Switch } from "@heroui/switch";
import { Flag02Icon, Tick02Icon } from "@icons";
import { useState } from "react";

import { cn } from "@/lib/utils";
import type { Priority } from "@/types/features/todoTypes";
import { AppIcon, PropertyRow } from "./TaskParts";
import { isRepeating, type Task } from "./taskModel";
import WhenField from "./WhenField";

type Update = (patch: Partial<Task>) => void;

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
      <Popover
        isOpen={isOpen}
        onOpenChange={setIsOpen}
        placement="bottom-start"
        offset={6}
        triggerScaleOnOpen={false}
      >
        <PopoverTrigger>
          <Button
            size="sm"
            variant="light"
            aria-label="Priority"
            disableAnimation
            className={cn(
              "-ml-2 h-8 min-w-0 flex-1 justify-start gap-1.5 px-2 text-sm font-normal data-[hover=true]:bg-zinc-800",
              isOpen && "bg-zinc-800",
              task.priority === "none" ? "text-zinc-500" : "text-zinc-200",
            )}
          >
            <Flag02Icon className={cn("size-4", current?.color)} />
            {current?.label}
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-44 rounded-xl bg-zinc-900 p-1">
          <div className="w-full">
            {PRIORITY.map((item) => (
              <Button
                key={item.key}
                size="sm"
                variant="light"
                onPress={() => {
                  update({ priority: item.key });
                  setIsOpen(false);
                }}
                className="h-8 w-full justify-start gap-2 rounded-lg px-2 text-sm font-normal text-zinc-200 data-[hover=true]:bg-zinc-800"
              >
                <Flag02Icon className={cn("size-4", item.color)} />
                {item.label}
                {item.key === task.priority && (
                  <Tick02Icon className="ml-auto size-4 text-zinc-400" />
                )}
              </Button>
            ))}
          </div>
        </PopoverContent>
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
        label={isYours ? "Nudges" : "Notify me"}
        hint={
          isYours
            ? "GAIA reminds you before this is due: in the app, and on Telegram, WhatsApp or wherever you talk to it."
            : "GAIA tells you when this finishes: in the app, and on Telegram, WhatsApp or wherever you talk to it."
        }
      >
        <Switch
          size="sm"
          aria-label={isYours ? "Nudges" : "Notify me"}
          isSelected={task.notify}
          onValueChange={(notify) => update({ notify })}
        />
      </PropertyRow>
      {task.source && (
        <PropertyRow label="From">
          <Button
            size="sm"
            variant="light"
            className="-ml-2 h-8 min-w-0 gap-1.5 px-2 text-sm font-normal text-zinc-200 data-[hover=true]:bg-zinc-800"
            startContent={<AppIcon id={task.source.app} size={15} />}
          >
            Open email
          </Button>
        </PropertyRow>
      )}
    </div>
  );
}

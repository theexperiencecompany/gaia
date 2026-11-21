"use client";

import { Input, TextArea } from "@heroui/react";
import { useState } from "react";

import { inputVariants } from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { toneVariants } from "@/components/shared/tone";
import { blankTask } from "./NewTask";
import { TaskIconTile } from "./TaskParts";
import TaskProperties from "./TaskProperties";
import type { Task } from "./taskModel";

/** Handing GAIA a task: what it's called and what to do. Nothing else is asked. */
export function NewGaiaTask({ onCreate }: { onCreate: (task: Task) => void }) {
  const [draft, setDraft] = useState<Task>(() => blankTask("gaia"));
  const update = (patch: Partial<Task>) => setDraft({ ...draft, ...patch });
  const instructions = draft.instructions?.trim() ?? "";
  const title = draft.title.trim() || instructions.split("\n")[0];

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 space-y-5 overflow-y-auto px-6 pt-2 pb-6">
        <div className="space-y-3">
          <TaskIconTile size={36} />
          <Input
            autoFocus
            aria-label="Task name"
            value={draft.title}
            onChange={(event) => update({ title: event.target.value })}
            placeholder="Name this task"
            className={inputVariants({
              variant: "inline",
              placeholder: "subtle",
              className: toneVariants({
                tone: "strong",
                className: "w-full text-2xl leading-8 font-medium",
              }),
            })}
          />
        </div>
        <TextArea
          aria-label="What should GAIA do?"
          value={draft.instructions ?? ""}
          onChange={(event) => update({ instructions: event.target.value })}
          placeholder="What should GAIA do?"
          rows={5}
          className={inputVariants({
            variant: "filled",
            placeholder: "faint",
            className: toneVariants({
              tone: "strong",
              className: "block w-full resize-none text-sm leading-6",
            }),
          })}
        />
        <TaskProperties task={draft} update={update} />
      </div>
      <div className="p-3">
        <GaiaButton
          variant="primary"
          fullWidth
          isDisabled={!title}
          onPress={() =>
            onCreate({ ...draft, title, status: "Getting started" })
          }
          className="font-medium"
        >
          Hand to GAIA
        </GaiaButton>
      </div>
    </div>
  );
}

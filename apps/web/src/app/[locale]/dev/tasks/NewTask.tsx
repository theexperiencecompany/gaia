"use client";

import { Button } from "@heroui/button";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/dropdown";
import { Input, Textarea } from "@heroui/input";
import { PlusSignIcon, UserIcon } from "@icons";
import { useEffect, useRef, useState } from "react";

import { GaiaMark, TaskIconTile } from "./TaskParts";
import TaskProperties from "./TaskProperties";
import type { Assignee, Task } from "./taskModel";

const BARE =
  "h-auto min-h-0 border-none bg-transparent px-0 py-0 shadow-none data-[hover=true]:bg-transparent group-data-[focus=true]:bg-transparent group-data-[focus-visible=true]:ring-0 group-data-[focus-visible=true]:ring-offset-0";

/** A task with nothing set: the starting point for every way of creating one. */
export function blankTask(assignee: Assignee): Task {
  return {
    id: crypto.randomUUID(),
    title: "",
    assignee,
    state: assignee === "you" ? "open" : "running",
    when: { kind: "anytime" },
    priority: "none",
    integrations: [],
    checklist: [],
    activity: [],
    runs: [],
    notify: true,
  };
}

/** The one question creating a task asks: who it's for. Everything else comes after. */
export function NewTaskButton({
  onPick,
}: {
  onPick: (assignee: Assignee) => void;
}) {
  return (
    <Dropdown placement="bottom-end">
      <DropdownTrigger>
        <Button
          size="sm"
          variant="flat"
          startContent={<PlusSignIcon className="size-4" />}
          className="bg-zinc-800 text-zinc-100"
        >
          New task
        </Button>
      </DropdownTrigger>
      <DropdownMenu
        aria-label="Who is the task for"
        onAction={(key) => onPick(key as Assignee)}
      >
        <DropdownItem
          key="you"
          description="A to-do you'll do yourself"
          startContent={<UserIcon className="size-5 text-zinc-400" />}
        >
          For me
        </DropdownItem>
        <DropdownItem
          key="gaia"
          description="Hand something to GAIA"
          startContent={<GaiaMark size={20} />}
        >
          For GAIA
        </DropdownItem>
      </DropdownMenu>
    </Dropdown>
  );
}

/** A to-do being typed, in the list where it will live. Enter keeps going; leaving it empty ends it. */
export function NewTodoRow({
  onCreate,
  onDone,
}: {
  onCreate: (title: string) => void;
  onDone: () => void;
}) {
  const [title, setTitle] = useState("");
  const input = useRef<HTMLInputElement>(null);
  // The button that opened this row takes focus back when its press ends, so focus after that.
  useEffect(() => {
    const timer = setTimeout(() => input.current?.focus(), 80);
    return () => clearTimeout(timer);
  }, []);
  const commit = () => {
    const text = title.trim();
    if (text) onCreate(text);
    setTitle("");
    return text;
  };

  return (
    <div className="flex gap-3.5 rounded-xl bg-white/[0.04] px-2 py-2">
      <span className="flex size-7 shrink-0 -translate-y-0.5 items-center justify-center">
        <span className="size-5 rounded-full border-2 border-dashed border-zinc-600" />
      </span>
      <Input
        ref={input}
        aria-label="New to-do"
        value={title}
        onValueChange={setTitle}
        onKeyDown={(event) => {
          if (event.key === "Enter") commit();
          if (event.key === "Escape") onDone();
        }}
        onBlur={() => {
          // Losing focus before the row ever had it is the opening button, not the user leaving.
          if (document.activeElement === input.current) return;
          commit();
          onDone();
        }}
        placeholder="What do you need to do?"
        variant="flat"
        classNames={{
          base: "min-w-0 flex-1",
          input: "text-[15px] text-zinc-100 placeholder:text-zinc-500",
          inputWrapper: `${BARE} h-7`,
        }}
      />
    </div>
  );
}

/** Handing GAIA a task: what it's called and what to do. Nothing else is asked. */
export function NewGaiaTask({ onCreate }: { onCreate: (task: Task) => void }) {
  const [draft, setDraft] = useState<Task>(() => blankTask("gaia"));
  const update = (patch: Partial<Task>) => setDraft({ ...draft, ...patch });
  const instructions = draft.instructions?.trim() ?? "";
  const title = draft.title.trim() || instructions.split("\n")[0];

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 space-y-5 overflow-y-auto px-6 pb-6 pt-2">
        <div className="space-y-3">
          <TaskIconTile size={36} />
          <Input
            autoFocus
            aria-label="Task name"
            value={draft.title}
            onValueChange={(value) => update({ title: value })}
            placeholder="Name this task"
            variant="flat"
            classNames={{
              input:
                "text-2xl font-medium text-zinc-100 placeholder:text-zinc-600",
              inputWrapper: BARE,
            }}
          />
        </div>
        <Textarea
          aria-label="What should GAIA do?"
          value={draft.instructions ?? ""}
          onValueChange={(value) => update({ instructions: value })}
          placeholder="What should GAIA do?"
          minRows={5}
          variant="flat"
          classNames={{
            input: "text-sm leading-6 text-zinc-100 placeholder:text-zinc-500",
            inputWrapper:
              "rounded-2xl bg-zinc-800 p-3.5 shadow-none data-[hover=true]:bg-zinc-800 group-data-[focus=true]:bg-zinc-800 group-data-[focus-visible=true]:ring-0 group-data-[focus-visible=true]:ring-offset-0",
          }}
        />
        <TaskProperties task={draft} update={update} />
      </div>
      <div className="p-3">
        <Button
          color="primary"
          fullWidth
          isDisabled={!title}
          onPress={() =>
            onCreate({ ...draft, title, status: "Getting started" })
          }
          className="font-medium"
        >
          Hand to GAIA
        </Button>
      </div>
    </div>
  );
}

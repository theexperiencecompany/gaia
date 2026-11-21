"use client";

import { Input, TextArea } from "@heroui/react";
import { useEffect, useRef, useState } from "react";

import { inputVariants } from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { toneVariants } from "@/components/shared/tone";
import { TaskIconTile } from "./TaskIconTile";
import { type Assignee, isRepeating, type Task } from "./taskModel";
import WhenField from "./WhenField";

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
    runs: [],
    notify: true,
  };
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
        onChange={(event) => setTitle(event.target.value)}
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
        className={inputVariants({
          variant: "inline",
          placeholder: "faint",
          className: toneVariants({
            tone: "strong",
            className: "h-7 min-w-0 flex-1 text-[15px]",
          }),
        })}
      />
    </div>
  );
}

/** Where a new GAIA task starts: repeating, waiting for its date, or at work now. */
function firstState(task: Task): Pick<Task, "state" | "status"> {
  if (isRepeating(task.when)) return { state: "standing" };
  if (task.when.kind === "at") return { state: "scheduled" };
  return { state: "running", status: "Getting started" };
}

/** Handing GAIA a task: what it's called, what to do, and when. Nothing else is asked. */
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
        <div>
          <WhenField
            when={draft.when}
            onChange={(when) => update({ when })}
            forGaia
          />
        </div>
      </div>
      <div className="p-3">
        <GaiaButton
          variant="primary"
          fullWidth
          isDisabled={!title}
          onPress={() => onCreate({ ...draft, title, ...firstState(draft) })}
          className="font-medium"
        >
          Hand to GAIA
        </GaiaButton>
      </div>
    </div>
  );
}

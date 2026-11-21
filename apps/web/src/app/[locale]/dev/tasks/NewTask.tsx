"use client";

import { Dropdown, Input } from "@heroui/react";
import { PlusSignIcon, UserIcon } from "@icons";
import { useEffect, useRef, useState } from "react";

import { inputVariants } from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { shapeVariants } from "@/components/shared/shape";
import { toneVariants } from "@/components/shared/tone";
import { GaiaMark } from "./TaskParts";
import type { Assignee, Task } from "./taskModel";

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

const NEW_FOR: {
  id: Assignee;
  label: string;
  description: string;
}[] = [
  { id: "you", label: "For me", description: "A to-do you'll do yourself" },
  { id: "gaia", label: "For GAIA", description: "Hand something to GAIA" },
];

/** The one question creating a task asks: who it's for. Everything else comes after. */
export function NewTaskButton({
  onPick,
}: {
  onPick: (assignee: Assignee) => void;
}) {
  return (
    <Dropdown>
      <GaiaButton size="sm" variant="tertiary" tone="strong">
        <PlusSignIcon className="size-4" />
        New task
      </GaiaButton>
      <Dropdown.Popover
        placement="bottom end"
        offset={7}
        className={shapeVariants({ shape: "lg" })}
      >
        <Dropdown.Menu
          aria-label="Who is the task for"
          onAction={(key) => {
            const picked = NEW_FOR.find((item) => item.id === key);
            if (picked) onPick(picked.id);
          }}
        >
          {NEW_FOR.map((item) => (
            <Dropdown.Item
              key={item.id}
              id={item.id}
              textValue={item.label}
              className="gap-2"
            >
              <span aria-hidden className="flex shrink-0">
                {item.id === "you" ? (
                  <UserIcon className="size-5 text-zinc-400" />
                ) : (
                  <GaiaMark size={20} />
                )}
              </span>
              <div className="flex flex-col">
                <span>{item.label}</span>
                <span className="text-xs text-zinc-400">
                  {item.description}
                </span>
              </div>
            </Dropdown.Item>
          ))}
        </Dropdown.Menu>
      </Dropdown.Popover>
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

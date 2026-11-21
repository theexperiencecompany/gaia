"use client";

import { Input } from "@heroui/react";
import { useEffect, useRef, useState } from "react";

import { inputVariants } from "@/components/shared/controlVariants";
import { toneVariants } from "@/components/shared/tone";
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

"use client";

import { Button } from "@heroui/button";
import { Checkbox } from "@heroui/checkbox";
import { Input, Textarea } from "@heroui/input";
import { Kbd } from "@heroui/kbd";
import { m } from "motion/react";
import { useEffect, useState } from "react";
import {
  CalendarCheckOut01Icon,
  Flag02Icon,
  Folder02Icon,
  Tag01Icon,
} from "@/icons";
import { type TodoDemoPhase, tdTx } from "./todoDemoConstants";

const FULL_TITLE = "Prepare Q3 investor pitch deck";
const TYPING_INTERVAL_MS = 55;

interface DemoTodoModalProps {
  phase: TodoDemoPhase;
}

export default function DemoTodoModal({ phase }: DemoTodoModalProps) {
  const [typedTitle, setTypedTitle] = useState("");

  useEffect(() => {
    let i = 0;
    setTypedTitle("");
    const id = setInterval(() => {
      i++;
      setTypedTitle(FULL_TITLE.slice(0, i));
      if (i >= FULL_TITLE.length) clearInterval(id);
    }, TYPING_INTERVAL_MS);
    return () => clearInterval(id);
  }, []);

  const isSubmitting = phase === "modal_submit";

  return (
    <m.div
      key="todo-modal"
      initial={{ opacity: 0, scale: 0.92, y: 20 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.95, y: -10 }}
      transition={{ type: "spring", stiffness: 350, damping: 30 }}
      style={{ willChange: "transform, opacity" }}
      className="mx-auto w-full max-w-lg overflow-hidden rounded-2xl border border-zinc-700/50 bg-zinc-900 shadow-2xl"
    >
      <div className="flex flex-col gap-5 px-6 pt-6 pb-4">
        <m.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.15, ...tdTx }}
        >
          <Input
            value={typedTitle}
            readOnly
            variant="underlined"
            placeholder="Title"
            classNames={{
              input:
                "text-2xl font-semibold text-zinc-100 placeholder:text-zinc-500",
              inputWrapper: "border-0 bg-transparent shadow-none px-0",
            }}
          />
        </m.div>

        <m.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.3, ...tdTx }}
        >
          <Textarea
            value="Research latest pitch formats, compile competitor data, generate slide deck in Google Docs, share draft link on Slack."
            readOnly
            variant="underlined"
            minRows={2}
            classNames={{
              input: "text-sm text-zinc-400",
              inputWrapper: "border-0 bg-transparent shadow-none px-0",
            }}
          />
        </m.div>

        <m.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.45, ...tdTx }}
          className="flex flex-wrap gap-2"
        >
          <Button
            size="sm"
            variant="flat"
            className="h-8 min-w-0 gap-1.5 rounded-lg bg-zinc-800 px-3 text-zinc-300 hover:bg-zinc-700"
            startContent={
              <Folder02Icon className="h-4 w-4 shrink-0 text-blue-400" />
            }
          >
            Work
          </Button>

          <Button
            size="sm"
            variant="flat"
            className="h-8 min-w-0 gap-1.5 rounded-lg bg-red-400/10 px-3 text-red-400 hover:bg-red-400/20"
            startContent={
              <Flag02Icon className="h-4 w-4 shrink-0 text-red-400" />
            }
          >
            High
          </Button>

          <Button
            size="sm"
            variant="flat"
            className="h-8 min-w-0 gap-1.5 rounded-lg bg-zinc-800 px-3 text-zinc-400 hover:bg-zinc-700"
            startContent={
              <CalendarCheckOut01Icon className="h-4 w-4 shrink-0 text-zinc-400" />
            }
          >
            Tomorrow
          </Button>

          <Button
            size="sm"
            variant="flat"
            className="h-8 min-w-0 gap-1.5 rounded-lg bg-zinc-800 px-3 text-zinc-400 hover:bg-zinc-700"
            startContent={
              <Tag01Icon className="h-4 w-4 shrink-0 text-zinc-400" />
            }
          >
            Work
          </Button>
        </m.div>

        <m.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.6, ...tdTx }}
          className="flex flex-col gap-1"
        >
          <p className="text-xs font-medium text-zinc-500 mb-1">Subtasks</p>

          <div className="flex items-center gap-2 py-1.5">
            <Checkbox color="success" size="sm" isReadOnly />
            <span className="text-sm text-zinc-300">
              Research pitch formats
            </span>
          </div>

          <div className="flex items-center gap-2 py-1.5">
            <Checkbox color="success" size="sm" isReadOnly />
            <span className="text-sm text-zinc-300">
              Compile competitor data
            </span>
          </div>

          <div className="flex items-center gap-2 py-1.5">
            <Checkbox color="success" size="sm" isReadOnly />
            <span className="text-sm text-zinc-300">
              Create Google Doc slides
            </span>
          </div>

          <div className="flex items-center gap-2 mt-1">
            <span className="text-zinc-600 text-base leading-none select-none">
              +
            </span>
            <span className="text-sm text-zinc-600">Add subtask...</span>
          </div>
        </m.div>
      </div>

      <div className="flex items-center justify-end gap-3 border-t border-zinc-800 px-6 py-3">
        <Button variant="flat" size="md">
          Cancel
        </Button>
        <m.div
          animate={isSubmitting ? { scale: [1, 0.96, 1] } : {}}
          transition={{ duration: 0.18 }}
        >
          <Button
            color="primary"
            size="md"
            className={isSubmitting ? "ring-2 ring-primary/60" : ""}
            endContent={<Kbd keys={["command", "enter"]} />}
          >
            Add Task
          </Button>
        </m.div>
      </div>
    </m.div>
  );
}

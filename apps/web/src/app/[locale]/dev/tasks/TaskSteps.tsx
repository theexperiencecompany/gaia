"use client";

import { Button } from "@heroui/button";
import { Checkbox } from "@heroui/checkbox";
import { Input } from "@heroui/input";
import { Cancel01Icon, PlusSignIcon } from "@icons";
import { type KeyboardEvent, useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import type { SubTask } from "@/types/features/todoTypes";
import { TaskIconTile } from "./TaskParts";
import type { Task } from "./taskModel";

type Update = (patch: Partial<Task>) => void;

/** Every line in the steps area: the same height, inset and hover, whatever it holds. */
const LINE =
  "-mx-2 flex min-h-9 items-center gap-3 rounded-lg px-2 transition-colors";

const MARK = "flex size-5 shrink-0 items-center justify-center";

const BARE =
  "h-7 min-h-7 border-none bg-transparent px-0 py-0 shadow-none data-[hover=true]:bg-transparent group-data-[focus=true]:bg-transparent group-data-[focus-visible=true]:ring-0 group-data-[focus-visible=true]:ring-offset-0";

const newStep = (title = ""): SubTask => ({
  id: crypto.randomUUID(),
  title,
  completed: false,
  created_at: new Date().toISOString(),
});

/**
 * A task's subtasks. The last line is always an empty one to type into, so adding
 * never moves anything; Enter inside an existing subtask starts one below it.
 */
export default function TaskSteps({
  task,
  update,
}: {
  task: Task;
  update: Update;
}) {
  const steps = task.checklist;
  const isYours = task.assignee === "you";
  const inputs = useRef(new Map<string, HTMLInputElement>());
  const [focusId, setFocusId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  useEffect(() => {
    if (!focusId) return;
    inputs.current.get(focusId)?.focus();
    setFocusId(null);
  }, [focusId]);

  const setSteps = (checklist: SubTask[]) => update({ checklist });
  const patch = (id: string, change: Partial<SubTask>) =>
    setSteps(
      steps.map((step) => (step.id === id ? { ...step, ...change } : step)),
    );

  const addAfter = (index: number) => {
    const step = newStep();
    setSteps([...steps.slice(0, index + 1), step, ...steps.slice(index + 1)]);
    setFocusId(step.id);
  };

  const remove = (index: number) => {
    setSteps(steps.filter((_, at) => at !== index));
    const neighbour = steps[index - 1] ?? steps[index + 1];
    if (neighbour) setFocusId(neighbour.id);
  };

  const onKeyDown = (event: KeyboardEvent, index: number) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addAfter(index);
    }
    if (event.key === "Backspace" && steps[index].title === "") {
      event.preventDefault();
      remove(index);
    }
  };

  const acceptOffer = () => {
    const step = newStep(task.offer);
    update({
      offer: undefined,
      checklist: [...steps, step],
      gaiaSteps: [...(task.gaiaSteps ?? []), step.id],
    });
  };

  if (steps.length === 0 && !task.offer && !isYours) return null;

  return (
    <div className="space-y-0.5">
      {steps.map((step, index) => {
        const byGaia = task.gaiaSteps?.includes(step.id);
        return (
          <div
            key={step.id}
            className={cn(
              LINE,
              "group hover:bg-white/[0.04] focus-within:bg-white/[0.04]",
            )}
          >
            <span className={MARK}>
              {byGaia ? (
                <TaskIconTile size={20} />
              ) : (
                <Checkbox
                  aria-label={step.completed ? "Mark not done" : "Mark done"}
                  radius="full"
                  size="sm"
                  isSelected={step.completed}
                  isReadOnly={!isYours}
                  onValueChange={(completed) => patch(step.id, { completed })}
                  classNames={{
                    base: "m-0 p-0",
                    wrapper: "m-0 before:border-zinc-600 after:bg-zinc-500",
                    icon: "text-zinc-900",
                  }}
                />
              )}
            </span>
            <Input
              ref={(node: HTMLInputElement | null) => {
                if (node) inputs.current.set(step.id, node);
                else inputs.current.delete(step.id);
              }}
              aria-label="Subtask"
              value={step.title}
              isReadOnly={!isYours || byGaia}
              onValueChange={(title) => patch(step.id, { title })}
              onKeyDown={(event) => onKeyDown(event, index)}
              variant="flat"
              classNames={{
                base: "min-w-0 flex-1",
                input: cn(
                  "text-sm",
                  step.completed
                    ? "!text-zinc-500 line-through decoration-zinc-600"
                    : "!text-zinc-200",
                ),
                inputWrapper: BARE,
              }}
            />
            {isYours && (
              <Button
                isIconOnly
                size="sm"
                variant="light"
                aria-label="Remove subtask"
                onPress={() => remove(index)}
                className="size-6 min-w-6 shrink-0 text-zinc-500 opacity-0 group-hover:opacity-100 data-[focus-visible=true]:opacity-100"
              >
                <Cancel01Icon className="size-3.5" />
              </Button>
            )}
          </div>
        );
      })}

      {task.offer && (
        <div className={cn(LINE, "items-start py-2")}>
          <span className={cn(MARK, "mt-0.5")}>
            <TaskIconTile size={20} />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-sm leading-6 text-zinc-400">{task.offer}</p>
            <div className="-ml-2 flex items-center">
              <Button
                size="sm"
                variant="light"
                onPress={acceptOffer}
                className="h-7 min-w-0 px-2 text-[13px] text-primary"
              >
                Let GAIA do it
              </Button>
              <Button
                size="sm"
                variant="light"
                onPress={() => update({ offer: undefined })}
                className="h-7 min-w-0 px-2 text-[13px] text-zinc-500"
              >
                Dismiss
              </Button>
            </div>
          </div>
        </div>
      )}

      {isYours && (
        <div className={LINE}>
          <span className={cn(MARK, "text-zinc-600")}>
            <PlusSignIcon className="size-4" />
          </span>
          <Input
            aria-label="Add a subtask"
            value={draft}
            onValueChange={setDraft}
            onKeyDown={(event) => {
              if (event.key !== "Enter" || !draft.trim()) return;
              setSteps([...steps, newStep(draft.trim())]);
              setDraft("");
            }}
            placeholder="Add a subtask"
            variant="flat"
            classNames={{
              base: "min-w-0 flex-1",
              input: "text-sm !text-zinc-200 placeholder:text-zinc-500",
              inputWrapper: BARE,
            }}
          />
        </div>
      )}
    </div>
  );
}

"use client";

import { Input } from "@heroui/react";
import { Cancel01Icon, PlusSignIcon } from "@icons";
import { type KeyboardEvent, useEffect, useRef, useState } from "react";

import { inputVariants } from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { toneVariants } from "@/components/shared/tone";
import { cn } from "@/lib/utils";
import type { SubTask } from "@/types/features/todoTypes";
import TaskCheckbox from "./TaskCheckbox";
import { TaskIconTile } from "./TaskIconTile";
import { NEEDS } from "./taskIcons";
import { needOf, type Task } from "./taskModel";

type Update = (patch: Partial<Task>) => void;

/** Every line in the subtasks area: the same height, inset and hover, whatever it holds. */
const LINE =
  "-mx-2 flex min-h-9 items-center gap-3 rounded-lg px-2 transition-colors";

const MARK = "flex size-5 shrink-0 items-center justify-center";

/** A subtask's text: edited in place, 28px tall, so a line never moves when you click into it. */
const subtaskField = (isDone: boolean, className?: string) =>
  inputVariants({
    variant: "inline",
    placeholder: "faint",
    className: toneVariants({
      tone: isDone ? "faint" : "bright",
      className: cn(
        "h-7 min-w-0 flex-1 text-sm",
        isDone && "line-through decoration-zinc-600",
        className,
      ),
    }),
  });

const newSubtask = (title = ""): SubTask => ({
  id: crypto.randomUUID(),
  title,
  completed: false,
  created_at: new Date().toISOString(),
});

/** A child task's own short state: what it needs from you, or GAIA's latest line. */
function shortStatus(child: Task): { text?: string; isNeed: boolean } {
  const need = needOf(child);
  if (need) return { text: NEEDS[need].label, isNeed: true };
  if (child.state === "paused") return { text: "Stopped", isNeed: false };
  return { text: child.status, isNeed: false };
}

/** A subtask GAIA owns: its mark, its name and its state; it opens as its own task. */
function ChildLine({
  child,
  onOpen,
}: {
  child: Task;
  onOpen: (task: Task) => void;
}) {
  const isDone = child.state === "done";
  const status = shortStatus(child);
  return (
    <div className="relative -mx-2">
      <GaiaButton
        aria-label={`Open ${child.title}`}
        variant="row"
        shape="sm"
        inset="none"
        onPress={() => onOpen(child)}
        className="absolute inset-0 h-full w-full min-w-0"
      />
      <div className="pointer-events-none relative flex min-h-9 items-start gap-3 px-2 py-1.5">
        <span className={MARK}>
          <TaskIconTile icon={child.icon} size={20} />
        </span>
        <span className="min-w-0 flex-1">
          <span
            className={cn(
              "block truncate text-sm leading-6",
              isDone
                ? "text-zinc-500 line-through decoration-zinc-600"
                : "text-zinc-200",
            )}
          >
            {child.title}
          </span>
          {status.text && !isDone && (
            <span
              className={cn(
                "block truncate text-xs leading-4",
                status.isNeed ? "text-amber-400" : "text-zinc-500",
              )}
            >
              {status.text}
            </span>
          )}
        </span>
      </div>
    </div>
  );
}

/**
 * A task's subtasks: its checklist, then the tasks GAIA owns under it. On your own
 * to-do the last line is always an empty one to type into, so adding never moves
 * anything; Enter inside an existing subtask starts one below it.
 */
export default function TaskSubtasks({
  task,
  update,
  childTasks,
  onOpen,
  onAcceptOffer,
}: {
  task: Task;
  update: Update;
  /** Tasks whose parent_id is this one. */
  childTasks: Task[];
  onOpen: (task: Task) => void;
  /** Turns GAIA's offer into a subtask GAIA owns. */
  onAcceptOffer: (title: string) => void;
}) {
  const subtasks = task.checklist;
  const isYours = task.assignee === "you";
  const inputs = useRef(new Map<string, HTMLInputElement>());
  const [focusId, setFocusId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  useEffect(() => {
    if (!focusId) return;
    inputs.current.get(focusId)?.focus();
    setFocusId(null);
  }, [focusId]);

  const setSubtasks = (checklist: SubTask[]) => update({ checklist });
  const patch = (id: string, change: Partial<SubTask>) =>
    setSubtasks(
      subtasks.map((item) => (item.id === id ? { ...item, ...change } : item)),
    );

  const addAfter = (index: number) => {
    const item = newSubtask();
    setSubtasks([
      ...subtasks.slice(0, index + 1),
      item,
      ...subtasks.slice(index + 1),
    ]);
    setFocusId(item.id);
  };

  const remove = (index: number) => {
    setSubtasks(subtasks.filter((_, at) => at !== index));
    const neighbour = subtasks[index - 1] ?? subtasks[index + 1];
    if (neighbour) setFocusId(neighbour.id);
  };

  const onKeyDown = (event: KeyboardEvent, index: number) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addAfter(index);
    }
    if (event.key === "Backspace" && subtasks[index].title === "") {
      event.preventDefault();
      remove(index);
    }
  };

  const acceptOffer = () => {
    if (task.offer) onAcceptOffer(task.offer);
  };

  if (
    subtasks.length === 0 &&
    childTasks.length === 0 &&
    !task.offer &&
    !isYours
  )
    return null;

  return (
    <div className="space-y-0.5">
      {subtasks.map((item, index) => (
        <div
          key={item.id}
          className={cn(
            LINE,
            "group focus-within:bg-white/[0.04] hover:bg-white/[0.04]",
          )}
        >
          <span className={MARK}>
            <TaskCheckbox
              label={item.completed ? "Mark not done" : "Mark done"}
              isSelected={item.completed}
              isReadOnly={!isYours}
              isSubtask
              onChange={(completed) => patch(item.id, { completed })}
            />
          </span>
          <Input
            ref={(node: HTMLInputElement | null) => {
              if (node) inputs.current.set(item.id, node);
              else inputs.current.delete(item.id);
            }}
            aria-label="Subtask"
            value={item.title}
            readOnly={!isYours}
            onChange={(event) => patch(item.id, { title: event.target.value })}
            onKeyDown={(event) => onKeyDown(event, index)}
            className={subtaskField(item.completed)}
          />
          {isYours && (
            <GaiaButton
              isIconOnly
              size="sm"
              variant="quiet"
              tone="faint"
              aria-label="Remove subtask"
              onPress={() => remove(index)}
              className="size-6 min-w-6 shrink-0 opacity-0 group-hover:opacity-100 data-[focus-visible=true]:opacity-100"
            >
              <Cancel01Icon className="size-3.5" />
            </GaiaButton>
          )}
        </div>
      ))}

      {childTasks.map((child) => (
        <ChildLine key={child.id} child={child} onOpen={onOpen} />
      ))}

      {task.offer && (
        <div className={cn(LINE, "items-start py-2")}>
          <span className={cn(MARK, "mt-0.5")}>
            <TaskIconTile size={20} />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-sm leading-6 text-zinc-400">{task.offer}</p>
            <div className="-ml-2 flex items-center">
              <GaiaButton
                size="sm"
                variant="quiet"
                tone="accent"
                inset="tight"
                onPress={acceptOffer}
                className="h-7 min-w-0 text-[13px]"
              >
                Let GAIA do it
              </GaiaButton>
              <GaiaButton
                size="sm"
                variant="quiet"
                tone="faint"
                inset="tight"
                onPress={() => update({ offer: undefined })}
                className="h-7 min-w-0 text-[13px]"
              >
                Dismiss
              </GaiaButton>
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
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key !== "Enter" || !draft.trim()) return;
              setSubtasks([...subtasks, newSubtask(draft.trim())]);
              setDraft("");
            }}
            placeholder="Add a subtask"
            className={subtaskField(false)}
          />
        </div>
      )}
    </div>
  );
}

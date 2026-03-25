"use client";

import { Accordion, AccordionItem } from "@heroui/accordion";
import { Chip } from "@heroui/chip";
import { Progress } from "@heroui/progress";
import {
  Cancel01Icon,
  CheckmarkCircle02Icon,
  DashedLineCircleIcon,
  Loading03Icon,
} from "@icons";
import { useMemo, useRef } from "react";
import { ChevronDown } from "@/components/shared/icons";
import type {
  TodoProgressData,
  TodoProgressItem,
} from "@/types/features/todoProgressTypes";

interface TodoProgressSectionProps {
  todo_progress: TodoProgressData;
  isStreaming?: boolean;
}

const STATUS_ICON_MAP: Record<
  TodoProgressItem["status"],
  React.ComponentType<{ className?: string }>
> = {
  completed: CheckmarkCircle02Icon,
  in_progress: Loading03Icon,
  pending: DashedLineCircleIcon,
  cancelled: Cancel01Icon,
};

const STATUS_COLOR: Record<TodoProgressItem["status"], string> = {
  completed: "text-emerald-400",
  in_progress: "text-primary",
  pending: "text-zinc-600",
  cancelled: "text-zinc-600",
};

function toTitleCase(str: string): string {
  return str
    .replace(/[-_]/g, " ")
    .replace(/\w\S*/g, (w) => w.charAt(0).toUpperCase() + w.slice(1));
}

function getProgressColor(
  pct: number,
): "default" | "primary" | "warning" | "success" {
  if (pct >= 100) return "success";
  if (pct >= 60) return "warning";
  if (pct > 0) return "primary";
  return "default";
}

function TaskRow({
  todo,
  isStreaming,
}: {
  todo: TodoProgressItem;
  isStreaming?: boolean;
}) {
  const StatusIcon = STATUS_ICON_MAP[todo.status];
  const shouldSpin = todo.status === "in_progress" && isStreaming;
  return (
    <div className="flex items-start gap-2">
      <div className={`shrink-0 mt-0.5 ${shouldSpin ? "animate-spin" : ""}`}>
        <StatusIcon className={`size-4 ${STATUS_COLOR[todo.status]}`} />
      </div>
      <span
        className={`text-xs leading-relaxed ${todo.status === "cancelled" ? "line-through text-zinc-600" : "text-zinc-300"}`}
      >
        {todo.content}
      </span>
    </div>
  );
}

function SourceTaskList({
  todos,
  isStreaming,
}: {
  todos: TodoProgressItem[];
  isStreaming?: boolean;
}) {
  return (
    <div className="space-y-1.5">
      {todos.map((todo) => (
        <TaskRow key={todo.id} todo={todo} isStreaming={isStreaming} />
      ))}
    </div>
  );
}

export default function TodoProgressSection({
  todo_progress,
  isStreaming,
}: TodoProgressSectionProps) {
  const sources = Object.keys(todo_progress);
  if (sources.length === 0) return null;

  const activeSources = sources.filter(
    (s) => todo_progress[s]?.todos && todo_progress[s].todos.length > 0,
  );
  if (activeSources.length === 0) return null;

  if (activeSources.length === 1) {
    return (
      <SingleSourceCard
        source={activeSources[0]}
        todos={todo_progress[activeSources[0]].todos}
        isStreaming={isStreaming}
      />
    );
  }

  return (
    <MultiSourceAccordion
      activeSources={activeSources}
      todo_progress={todo_progress}
      isStreaming={isStreaming}
    />
  );
}

function SingleSourceCard({
  source,
  todos,
  isStreaming,
}: {
  source: string;
  todos: TodoProgressItem[];
  isStreaming?: boolean;
}) {
  const completedCount = todos.filter((t) => t.status === "completed").length;
  const pct = todos.length > 0 ? (completedCount / todos.length) * 100 : 0;
  const progressColor = getProgressColor(pct);

  return (
    <div className="mt-2 mb-2 animate-scale-in rounded-3xl bg-zinc-800/70 backdrop-blur-xl p-4 w-full max-w-96">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium text-zinc-400">
          {toTitleCase(source)}
        </span>
        <Chip
          size="sm"
          variant="flat"
          classNames={{
            base: "bg-zinc-700/60",
            content: "text-xs text-zinc-400",
          }}
        >
          {completedCount}/{todos.length}
        </Chip>
      </div>
      <Progress size="sm" value={pct} color={progressColor} className="mb-3" />
      <SourceTaskList todos={todos} isStreaming={isStreaming} />
    </div>
  );
}

function MultiSourceAccordion({
  activeSources,
  todo_progress,
  isStreaming,
}: {
  activeSources: string[];
  todo_progress: TodoProgressData;
  isStreaming?: boolean;
}) {
  const prevDataRef = useRef<TodoProgressData>({});

  const defaultExpandedKey = useMemo(() => {
    let latest: string | null = null;
    for (const key of activeSources) {
      if (todo_progress[key] !== prevDataRef.current[key]) {
        latest = key;
      }
    }
    prevDataRef.current = todo_progress;
    return latest ?? activeSources[activeSources.length - 1];
  }, [activeSources, todo_progress]);

  return (
    <div className="mt-2 mb-2 animate-scale-in rounded-2xl bg-zinc-800/70 backdrop-blur-xl p-1 w-full max-w-96">
      <Accordion
        defaultExpandedKeys={[defaultExpandedKey]}
        className="px-0"
        itemClasses={{
          base: "px-2",
          title: "text-xs font-medium text-zinc-400",
          content: "pb-2 pt-0",
          trigger: "py-2",
          indicator: "size-3 text-zinc-500",
        }}
      >
        {activeSources.map((source) => {
          const todos = todo_progress[source].todos;
          const completedCount = todos.filter(
            (t) => t.status === "completed",
          ).length;
          const pct =
            todos.length > 0 ? (completedCount / todos.length) * 100 : 0;
          const progressColor = getProgressColor(pct);

          return (
            <AccordionItem
              key={source}
              indicator={({ isOpen }) => (
                <ChevronDown
                  className={`size-3 text-zinc-500 transition-transform duration-200 ${isOpen ? "rotate-180" : ""}`}
                />
              )}
              title={
                <div className="flex items-center gap-2 w-full pr-1">
                  <span className="text-xs font-medium text-zinc-400 min-w-0 flex-1 truncate">
                    {toTitleCase(source)}
                  </span>
                  <Progress
                    size="sm"
                    value={pct}
                    color={progressColor}
                    className="w-16 shrink-0"
                  />
                  <Chip
                    size="sm"
                    variant="flat"
                    classNames={{
                      base: "bg-zinc-700/60 shrink-0",
                      content: "text-xs text-zinc-500",
                    }}
                  >
                    {completedCount}/{todos.length}
                  </Chip>
                </div>
              }
            >
              <SourceTaskList todos={todos} isStreaming={isStreaming} />
            </AccordionItem>
          );
        })}
      </Accordion>
    </div>
  );
}

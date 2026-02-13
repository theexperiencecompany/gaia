"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { formatDistanceToNow } from "date-fns";
import { useMemo, useState } from "react";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import {
  ArrowDown01Icon,
  CalendarCheckOut01Icon,
  CheckmarkCircle02Icon,
  Delete02Icon,
  Flag02Icon,
  Folder02Icon,
  PlusSignIcon,
  Tag01Icon,
  ZapIcon,
} from "@/icons";
import {
  DEMO_PROJECTS,
  DEMO_TODOS,
  type DemoTodo,
} from "./todosDemoConstants";

const priorityRingColors = {
  high: "border-red-500",
  medium: "border-yellow-500",
  low: "border-blue-500",
  none: "border-zinc-500",
} as const;

const priorityChipClassNames = {
  high: "text-red-400 bg-red-400/10",
  medium: "text-yellow-400 bg-yellow-400/10",
  low: "text-blue-400 bg-blue-400/10",
  none: "text-zinc-500",
} as const;

function formatDueDate(dateString: string): string {
  const date = new Date(dateString);
  const today = new Date();
  const tomorrow = new Date(today);
  tomorrow.setDate(today.getDate() + 1);

  if (date.toDateString() === today.toDateString()) {
    return "Today";
  }
  if (date.toDateString() === tomorrow.toDateString()) {
    return "Tomorrow";
  }
  return date.toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

function isDueToday(dateString: string): boolean {
  const date = new Date(dateString);
  const today = new Date();
  return (
    date.getFullYear() === today.getFullYear() &&
    date.getMonth() === today.getMonth() &&
    date.getDate() === today.getDate()
  );
}

function isOverdue(dateString: string): boolean {
  const date = new Date(dateString);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  date.setHours(0, 0, 0, 0);
  return date < today;
}

function DemoTodoItem({
  todo,
  isSelected,
  onClick,
}: {
  todo: DemoTodo;
  isSelected: boolean;
  onClick: () => void;
}) {
  const project = DEMO_PROJECTS.find((p) => p.id === todo.project_id);

  return (
    <div
      className={`w-full cursor-pointer p-4 pl-5 transition-all hover:bg-zinc-800/50 ${
        isSelected ? "bg-primary/5 ring-2 ring-primary" : ""
      } ${todo.completed ? "opacity-30" : ""}`}
      onClick={onClick}
    >
      <div className="flex h-full items-start gap-3">
        {/* Checkbox circle */}
        <div
          className={`mt-1 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border-2 border-dashed ${priorityRingColors[todo.priority]}`}
        >
          {todo.completed && (
            <div className="h-full w-full rounded-full bg-green-500" />
          )}
        </div>

        {/* Content */}
        <div className="min-w-0 flex-1">
          <h4
            className={`text-base font-medium ${
              todo.completed ? "text-zinc-500 line-through" : ""
            }`}
          >
            {todo.title}
          </h4>
          {todo.description && (
            <p className="mt-1 text-xs text-zinc-500">{todo.description}</p>
          )}

          {/* Metadata chips */}
          <div className="mt-2 flex flex-wrap items-center gap-1">
            {todo.due_date && (
              <Chip
                className="flex items-center px-1 text-zinc-400"
                size="sm"
                radius="sm"
                color={
                  isDueToday(todo.due_date)
                    ? "success"
                    : isOverdue(todo.due_date)
                      ? "danger"
                      : "default"
                }
                variant="flat"
                startContent={
                  <CalendarCheckOut01Icon
                    width={16}
                    height={16}
                    className="mx-1"
                  />
                }
              >
                {formatDueDate(todo.due_date)}
              </Chip>
            )}

            {todo.priority !== "none" && (
              <Chip
                size="sm"
                variant="flat"
                radius="sm"
                className={`px-2 ${priorityChipClassNames[todo.priority]}`}
                startContent={
                  <Flag02Icon width={15} height={15} className="mx-1" />
                }
              >
                {todo.priority.charAt(0).toUpperCase() +
                  todo.priority.slice(1)}
              </Chip>
            )}

            {project && (
              <Chip
                size="sm"
                variant="flat"
                className="px-1 text-zinc-400"
                radius="sm"
                style={{ color: project.color }}
                startContent={
                  <Folder02Icon width={15} height={15} className="mx-1" />
                }
              >
                {project.name}
              </Chip>
            )}

            {todo.labels.map((label) => (
              <Chip
                key={label}
                size="sm"
                variant="flat"
                className="flex items-center px-1 text-zinc-400"
                radius="sm"
                startContent={
                  <Tag01Icon width={17} height={17} className="mx-1" />
                }
              >
                {label.charAt(0).toUpperCase() + label.slice(1)}
              </Chip>
            ))}

            {todo.subtasks.length > 0 && (
              <Chip
                size="sm"
                variant="flat"
                className="px-1 text-zinc-400"
                radius="sm"
                startContent={
                  <CheckmarkCircle02Icon
                    width={15}
                    height={15}
                    className="mx-1"
                  />
                }
              >
                {todo.subtasks.filter((s) => s.completed).length}/
                {todo.subtasks.length} subtasks
              </Chip>
            )}
          </div>
        </div>

        {/* Workflow category icons */}
        {todo.workflow_categories && todo.workflow_categories.length > 0 && (
          <div className="flex min-h-8 items-center -space-x-1.5 self-center">
            {todo.workflow_categories.slice(0, 3).map((category, index) => {
              const IconComponent = getToolCategoryIcon(category, {
                width: 22,
                height: 22,
              });
              return IconComponent ? (
                <div
                  key={category}
                  className="relative flex min-w-7 items-center justify-center"
                  style={{
                    rotate:
                      todo.workflow_categories!.length > 1
                        ? index % 2 === 0
                          ? "8deg"
                          : "-8deg"
                        : "0deg",
                    zIndex: index,
                  }}
                >
                  {IconComponent}
                </div>
              ) : null;
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function DemoFieldChip({
  icon,
  label,
  color,
}: {
  icon: React.ReactNode;
  label?: string;
  color?: string;
}) {
  return (
    <button
      type="button"
      className={`flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-sm transition-colors ${
        color ? "" : "bg-zinc-800 text-zinc-500"
      } hover:bg-zinc-700 cursor-pointer`}
      style={
        color
          ? { backgroundColor: `${color}20`, color }
          : undefined
      }
    >
      {icon}
      {label && <span className="truncate">{label}</span>}
      <ArrowDown01Icon width={14} height={14} className="shrink-0 opacity-50" />
    </button>
  );
}

function DemoTodoSidebar({
  todo,
  onClose,
}: {
  todo: DemoTodo;
  onClose: () => void;
}) {
  const project = DEMO_PROJECTS.find((p) => p.id === todo.project_id);

  const priorityColor = {
    high: "#ef4444",
    medium: "#eab308",
    low: "#3b82f6",
    none: undefined,
  }[todo.priority];

  return (
    <div
      className="flex h-full w-[300px] shrink-0 flex-col border-l border-zinc-800"
      style={{ backgroundColor: "#141414" }}
    >
      <div className="flex-1 overflow-y-auto pl-6 pr-3 pt-4">
        <div className="space-y-4">
          {/* Checkbox + Title */}
          <div className="flex items-start gap-1">
            <div
              className={`mt-1.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 border-dashed ${priorityRingColors[todo.priority]}`}
            >
              {todo.completed && (
                <div className="h-full w-full rounded-full bg-green-500" />
              )}
            </div>
            <h2
              className={`cursor-pointer text-2xl leading-tight font-medium transition-colors hover:text-zinc-200 ${
                todo.completed
                  ? "text-zinc-500 line-through"
                  : "text-zinc-100"
              }`}
            >
              {todo.title}
            </h2>
          </div>

          {/* Description */}
          <p
            className={`cursor-pointer text-sm leading-relaxed transition-colors hover:text-zinc-300 ${
              todo.completed ? "text-zinc-600" : "text-zinc-400"
            }`}
          >
            {todo.description || "Add a description..."}
          </p>

          {/* Field chips row - dropdown style like real TodoFieldsRow */}
          <div className="flex flex-wrap gap-2 py-2">
            <DemoFieldChip
              icon={
                <Folder02Icon
                  width={18}
                  height={18}
                  style={{ color: project?.color || "#71717a" }}
                />
              }
              label={project?.name}
              color={project ? "#3b82f6" : undefined}
            />
            <DemoFieldChip
              icon={
                <Flag02Icon
                  width={18}
                  height={18}
                  style={{ color: priorityColor || "#71717a" }}
                />
              }
              label={
                todo.priority !== "none"
                  ? todo.priority.charAt(0).toUpperCase() +
                    todo.priority.slice(1)
                  : undefined
              }
              color={priorityColor}
            />
            <DemoFieldChip
              icon={
                <CalendarCheckOut01Icon
                  width={18}
                  height={18}
                />
              }
              label={todo.due_date ? formatDueDate(todo.due_date) : undefined}
              color={
                todo.due_date
                  ? isDueToday(todo.due_date)
                    ? "#22c55e"
                    : isOverdue(todo.due_date)
                      ? "#ef4444"
                      : undefined
                  : undefined
              }
            />
            <DemoFieldChip
              icon={<Tag01Icon width={18} height={18} />}
              label={
                todo.labels.length > 0
                  ? `${todo.labels.length} label${todo.labels.length > 1 ? "s" : ""}`
                  : undefined
              }
              color={todo.labels.length > 0 ? "#3b82f6" : undefined}
            />
          </div>

          {/* Subtasks section */}
          <div className="border-y border-zinc-800 py-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium text-zinc-300">
                Subtasks
                {todo.subtasks.length > 0 &&
                  ` (${todo.subtasks.filter((s) => s.completed).length}/${todo.subtasks.length})`}
              </span>
            </div>
            {todo.subtasks.map((st) => (
              <div
                key={st.id}
                className="flex items-center gap-2 rounded-lg p-2 hover:bg-zinc-800/50"
              >
                <div
                  className={`h-3.5 w-3.5 shrink-0 rounded-full border ${
                    st.completed
                      ? "border-green-500 bg-green-500"
                      : "border-dashed border-zinc-500"
                  }`}
                />
                <span
                  className={`text-sm ${
                    st.completed
                      ? "text-zinc-500 line-through"
                      : "text-zinc-300"
                  }`}
                >
                  {st.title}
                </span>
              </div>
            ))}
            {/* Add subtask input placeholder */}
            <div className="mt-2 flex items-center gap-2 rounded-lg px-2 py-1.5">
              <PlusSignIcon width={14} height={14} className="text-zinc-600" />
              <span className="text-sm text-zinc-600">Add subtask...</span>
            </div>
          </div>

          {/* Workflow section */}
          {todo.workflow_categories &&
            todo.workflow_categories.length > 0 && (
              <div className="space-y-2">
                <div className="flex items-center gap-1">
                  <ZapIcon width={16} height={16} className="text-zinc-400" />
                  <span className="text-sm font-normal text-zinc-400">
                    Suggested Workflow
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  {todo.workflow_categories.map((cat, i) => {
                    const IconComponent = getToolCategoryIcon(cat, {
                      width: 20,
                      height: 20,
                    });
                    return IconComponent ? (
                      <div key={cat} style={{ zIndex: i }}>
                        {IconComponent}
                      </div>
                    ) : null;
                  })}
                </div>
              </div>
            )}
        </div>
      </div>

      {/* Footer: created date + delete */}
      <div className="flex items-center justify-between p-3">
        <span className="text-xs text-zinc-600">
          Created{" "}
          {formatDistanceToNow(new Date(todo.created_at), {
            addSuffix: true,
          })}
        </span>
        <Button
          isIconOnly
          color="danger"
          size="sm"
          variant="flat"
          aria-label="Delete todo"
        >
          <Delete02Icon className="size-5" />
        </Button>
      </div>
    </div>
  );
}

export default function DemoTodosView() {
  const [selectedTodo, setSelectedTodo] = useState<DemoTodo | null>(null);

  const sortedTodos = useMemo(() => {
    const priorityOrder = { high: 0, medium: 1, low: 2, none: 3 };
    return [...DEMO_TODOS].sort((a, b) => {
      if (a.completed !== b.completed) return a.completed ? 1 : -1;
      return priorityOrder[a.priority] - priorityOrder[b.priority];
    });
  }, []);

  return (
    <div className="flex h-full w-full">
      {/* Main todo list */}
      <div className="min-w-0 flex-1 overflow-y-auto px-4">
        <div className="w-full space-y-1 divide-y divide-zinc-800 py-4">
          {sortedTodos.map((todo) => (
            <DemoTodoItem
              key={todo.id}
              todo={todo}
              isSelected={selectedTodo?.id === todo.id}
              onClick={() =>
                setSelectedTodo(
                  selectedTodo?.id === todo.id ? null : todo,
                )
              }
            />
          ))}
        </div>
      </div>

      {/* Right sidebar - only when a todo is selected */}
      {selectedTodo && (
        <DemoTodoSidebar
          todo={selectedTodo}
          onClose={() => setSelectedTodo(null)}
        />
      )}
    </div>
  );
}

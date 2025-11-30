"use client";

import { Checkbox } from "@heroui/checkbox";
import { Chip } from "@heroui/chip";
import {
  CalendarCheckOut01Icon,
  CheckmarkCircle02Icon,
  ChevronRight,
  Flag02Icon,
  Folder02Icon,
  Tag01Icon,
} from "@/icons";
import { posthog } from "@/lib";
import {
  Priority,
  type Project,
  type Todo,
  type TodoUpdate,
} from "@/types/features/todoTypes";
import { formatDate } from "@/utils";

interface TodoItemProps {
  todo: Todo;
  projects: Project[];
  isSelected: boolean;
  onUpdate: (todoId: string, updates: TodoUpdate) => void;
  // onDelete: (todoId: string) => void;
  // onEdit?: (todo: Todo) => void;
  onClick?: (todo: Todo) => void;
}

const priorityColors = {
  [Priority.HIGH]: "danger",
  [Priority.MEDIUM]: "warning",
  [Priority.LOW]: "primary",
  [Priority.NONE]: "default",
} as const;

const priorityRingColors = {
  [Priority.HIGH]: "border-red-500",
  [Priority.MEDIUM]: "border-yellow-500",
  [Priority.LOW]: "border-blue-500",
  [Priority.NONE]: "border-zinc-500",
} as const;

export default function TodoItem({
  todo,
  projects,
  isSelected,
  onUpdate,
  // onDelete,
  // onEdit,
  onClick,
}: TodoItemProps) {
  const handleToggleComplete = (e: React.ChangeEvent<HTMLInputElement>) => {
    e.stopPropagation();
    const newCompletedState = !todo.completed;

    // Track todo completion toggle
    posthog.capture("todos:toggled", {
      todo_id: todo.id,
      completed: newCompletedState,
      priority: todo.priority,
      had_due_date: !!todo.due_date,
    });

    onUpdate(todo.id, { completed: newCompletedState });
  };

  const isOverdue =
    todo.due_date && new Date(todo.due_date) < new Date() && !todo.completed;

  const isToday =
    todo.due_date &&
    !todo.completed &&
    (() => {
      const d = new Date(todo.due_date);
      const now = new Date();
      return (
        d.getFullYear() === now.getFullYear() &&
        d.getMonth() === now.getMonth() &&
        d.getDate() === now.getDate()
      );
    })();

  return (
    <div
      className={`pointer-events-auto w-full cursor-pointer p-4 pl-5 mb-0 transition-all ${
        isSelected ? "bg-primary/5 ring-2 ring-primary" : "hover:bg-content2/70"
      } ${todo.completed ? "opacity-30" : ""}`}
      onClick={() => {
        onClick?.(todo);
      }}
    >
      <div className="flex h-full items-start gap-3">
        <div onClick={(e) => e.stopPropagation()}>
          <Checkbox
            isSelected={todo.completed}
            onChange={handleToggleComplete}
            color={todo.completed ? "default" : priorityColors[todo.priority]}
            radius="full"
            classNames={{
              wrapper: `mt-1 ${todo.completed ? "" : `${priorityRingColors[todo.priority]} border-dashed! border-1 before:border-0! bg-zinc-900`}`,
              label: "w-[30vw]",
            }}
          />
        </div>

        <div className="min-w-0 flex-1">
          <div>
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
          </div>

          {(todo.priority !== Priority.NONE ||
            todo.due_date ||
            todo.labels.length > 0) && (
            <div className="mt-2 flex flex-wrap items-center gap-1">
              {todo.due_date && (
                <Chip
                  className="flex items-center text-zinc-400 px-1"
                  size="sm"
                  radius="sm"
                  color={isToday ? "success" : isOverdue ? "danger" : "default"}
                  variant="flat"
                  startContent={
                    <CalendarCheckOut01Icon
                      width={16}
                      height={16}
                      className="mx-1"
                    />
                  }
                >
                  {formatDate(todo.due_date)}
                </Chip>
              )}

              {projects?.find((project) => project?.id === todo.project_id) && (
                <Chip
                  size="sm"
                  variant="flat"
                  className=" text-zinc-400 px-1"
                  radius="sm"
                  style={{
                    color: projects?.find((p) => p.id === todo.project_id)
                      ?.color,
                  }}
                  startContent={
                    <Folder02Icon width={15} height={15} className="mx-1" />
                  }
                >
                  {projects?.find((p) => p.id === todo.project_id)?.name}
                </Chip>
              )}

              <div className="flex items-center gap-1">
                {todo.labels.map((label) => (
                  <Chip
                    key={label}
                    size="sm"
                    variant="flat"
                    className="flex items-center text-zinc-400 px-1"
                    radius="sm"
                    startContent={
                      <Tag01Icon width={17} height={17} className="mx-1" />
                    }
                  >
                    {label.charAt(0).toUpperCase() + label.slice(1)}
                  </Chip>
                ))}
              </div>

              {!!todo.priority && todo.priority !== "none" && (
                <div className="flex items-center gap-1">
                  <Chip
                    size="sm"
                    variant="flat"
                    radius="sm"
                    className={`px-2 ${
                      todo.priority === Priority.HIGH
                        ? "text-red-400 bg-red-400/10"
                        : todo.priority === Priority.MEDIUM
                          ? "text-yellow-400 bg-yellow-400/10"
                          : todo.priority === Priority.LOW
                            ? "text-blue-400 bg-blue-400/10"
                            : "text-zinc-500"
                    }`}
                    startContent={
                      <Flag02Icon width={15} height={15} className="mx-1" />
                    }
                  >
                    {todo.priority.charAt(0).toUpperCase() +
                      todo.priority.slice(1)}
                  </Chip>
                </div>
              )}

              {/* Subtasks Count */}
              {todo.subtasks.length > 0 && (
                <Chip
                  size="sm"
                  variant="flat"
                  className=" text-zinc-400 px-1"
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
          )}
        </div>

        <div
          onClick={(e) => e.stopPropagation()}
          className="flex h-full min-h-full justify-center items-center self-center"
        >
          <ChevronRight width={20} height={20} className="text-zinc-400" />
        </div>
      </div>
    </div>
  );
}

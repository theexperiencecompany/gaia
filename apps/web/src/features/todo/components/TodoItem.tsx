"use client";

import { Checkbox } from "@heroui/checkbox";
import { Chip } from "@heroui/chip";
import {
  AiBrainIcon,
  AlertCircleIcon,
  CalendarCheckOut01Icon,
  CheckmarkCircle02Icon,
  Clock01Icon,
  Flag02Icon,
  Folder02Icon,
  Tag01Icon,
} from "@icons";
import { formatDistanceToNow } from "date-fns";
import { memo, useMemo } from "react";
import { ChevronRight } from "@/components/shared/icons";
import { useUser } from "@/features/auth/hooks/useUser";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { getBrowserTimezone } from "@/lib/timezone";
import { cn } from "@/lib/utils";
import {
  Priority,
  type Project,
  type Todo,
  type TodoUpdate,
} from "@/types/features/todoTypes";
import { formatDate } from "@/utils/date/dateUtils";
import { TodoTitle } from "./TodoTitle";

interface TodoItemProps {
  todo: Todo;
  projects: Project[];
  isSelected: boolean;
  onUpdate: (todoId: string, updates: TodoUpdate) => void;
  // onDelete: (todoId: string) => void;
  // onEdit?: (todo: Todo) => void;
  onClick?: (todo: Todo) => void;
  onPrefetchWorkflow?: (todoId: string) => void;
  className?: string;
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

// Intl.DateTimeFormat is expensive to build; cache one per timezone instead
// of rebuilding on every call.
const scheduledLabelFormatters = new Map<string, Intl.DateTimeFormat>();

const getScheduledLabelFormatter = (timeZone: string): Intl.DateTimeFormat => {
  const cached = scheduledLabelFormatters.get(timeZone);
  if (cached) return cached;
  const formatter = new Intl.DateTimeFormat("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
    timeZone,
  });
  scheduledLabelFormatters.set(timeZone, formatter);
  return formatter;
};

const formatScheduledLabel = (
  scheduledAt: string | null | undefined,
  timezone: string | undefined,
): string | undefined => {
  if (!scheduledAt) return undefined;
  const resolvedTimezone =
    timezone && timezone.trim() !== "" ? timezone : getBrowserTimezone();
  return getScheduledLabelFormatter(resolvedTimezone).format(
    new Date(scheduledAt),
  );
};

// Fanned-out category icons shown on the right edge of a todo row.
function WorkflowCategoryIcons({ categories }: { categories: string[] }) {
  return (
    <div className="flex min-h-8 items-center -space-x-1.5 self-center">
      {categories.slice(0, 3).map((category, index) => {
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
                categories.length > 1
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
      {categories.length > 3 && (
        <div className="z-0 flex size-[28px] min-h-[28px] min-w-[28px] items-center justify-center rounded-lg bg-zinc-700/60 text-xs text-foreground-500">
          +{categories.length - 3}
        </div>
      )}
    </div>
  );
}

export default memo(function TodoItem({
  todo,
  projects,
  isSelected,
  onUpdate,
  // onDelete,
  // onEdit,
  onClick,
  onPrefetchWorkflow,
  className,
}: TodoItemProps) {
  const handleToggleComplete = (e: React.ChangeEvent<HTMLInputElement>) => {
    e.stopPropagation();
    const newCompletedState = !todo.completed;

    onUpdate(todo.id, { completed: newCompletedState });
  };

  const user = useUser();
  // Format scheduled time in the user's preferred timezone so it matches the
  // task-edit modal / ScheduledFieldChip instead of the browser's local timezone.
  const scheduledLabel = useMemo(
    () => formatScheduledLabel(todo.scheduled_at, user?.timezone),
    [todo.scheduled_at, user?.timezone],
  );

  const todoProject = projects?.find((p) => p.id === todo.project_id);

  const isOverdue = useMemo(
    () =>
      !!todo.due_date &&
      new Date(todo.due_date) < new Date() &&
      !todo.completed,
    [todo.due_date, todo.completed],
  );

  const isToday = useMemo(() => {
    if (!todo.due_date || todo.completed) return false;
    const d = new Date(todo.due_date);
    const now = new Date();
    return (
      d.getFullYear() === now.getFullYear() &&
      d.getMonth() === now.getMonth() &&
      d.getDate() === now.getDate()
    );
  }, [todo.due_date, todo.completed]);

  return (
    <div
      className={cn(
        "pointer-events-auto relative w-full rounded-xl p-2 pl-3 mb-0 group",
        isSelected ? "bg-zinc-800/50" : "hover:bg-zinc-800/50",
        todo.completed && "opacity-30",
        className,
      )}
      style={{ contentVisibility: "auto", containIntrinsicSize: "0 80px" }}
      onMouseEnter={() => onPrefetchWorkflow?.(todo.id)}
    >
      <button
        type="button"
        aria-label={`Open todo ${todo.title}`}
        className="absolute inset-0 z-10 rounded-xl"
        onClick={() => onClick?.(todo)}
      />
      <div className="pointer-events-none relative z-20 flex h-full items-start gap-2">
        <div className="pointer-events-auto">
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
              style={{
                display: "-webkit-box",
                WebkitBoxOrient: "vertical",
                WebkitLineClamp: 2,
                overflow: "hidden",
              }}
              className={`text-base font-normal ${
                todo.completed ? "text-zinc-500 line-through" : ""
              }`}
            >
              <TodoTitle title={todo.title} />
            </h4>
            {todo.description && (
              <p className="mt-1 text-xs text-zinc-500 line-clamp-1">
                {todo.description}
              </p>
            )}
          </div>

          {(todo.priority !== Priority.NONE ||
            todo.due_date ||
            todo.scheduled_at ||
            todo.expires_at ||
            todo.vfs_path ||
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

              {todo.scheduled_at && (
                <Chip
                  className="flex items-center text-zinc-400 px-1"
                  size="sm"
                  radius="sm"
                  color="primary"
                  variant="flat"
                  startContent={
                    <Clock01Icon width={16} height={16} className="mx-1" />
                  }
                >
                  {scheduledLabel}
                </Chip>
              )}

              {todo.expires_at && (
                <Chip
                  className="flex items-center text-zinc-400 px-1"
                  size="sm"
                  radius="sm"
                  color="warning"
                  variant="flat"
                  startContent={
                    <AlertCircleIcon width={16} height={16} className="mx-1" />
                  }
                >
                  Expires{" "}
                  {formatDistanceToNow(new Date(todo.expires_at), {
                    addSuffix: true,
                  })}
                </Chip>
              )}

              {todo.vfs_path && (
                <Chip
                  className="flex items-center text-primary px-1"
                  size="sm"
                  radius="sm"
                  color="primary"
                  variant="flat"
                  startContent={
                    <AiBrainIcon width={14} height={14} className="mx-1" />
                  }
                >
                  Tracked
                </Chip>
              )}

              {todoProject && (
                <Chip
                  size="sm"
                  variant="flat"
                  className=" text-zinc-400 px-1"
                  radius="sm"
                  style={{ color: todoProject.color }}
                  startContent={
                    <Folder02Icon width={15} height={15} className="mx-1" />
                  }
                >
                  {todoProject.name}
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
                    className={`px-2 ${todo.priority === Priority.HIGH ? "text-red-400 bg-red-400/10" : todo.priority === Priority.MEDIUM ? "text-yellow-400 bg-yellow-400/10" : todo.priority === Priority.LOW ? "text-blue-400 bg-blue-400/10" : "text-zinc-500"}`}
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

        {/* Workflow Category Icons */}
        {todo.workflow_categories && todo.workflow_categories.length > 0 && (
          <WorkflowCategoryIcons categories={todo.workflow_categories} />
        )}

        <div
          onClick={(e) => e.stopPropagation()}
          className="flex h-full min-h-full justify-center items-center self-center group-hover:opacity-100 opacity-0 transition"
        >
          <ChevronRight width={20} height={20} className="text-zinc-400" />
        </div>
      </div>
    </div>
  );
});

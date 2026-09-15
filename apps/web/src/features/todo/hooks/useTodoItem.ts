"use client";

import { useMemo } from "react";
import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import { getBrowserTimezone } from "@/lib/timezone";
import {
  Priority,
  type Project,
  type Todo,
  type TodoUpdate,
} from "@/types/features/todoTypes";

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

interface UseTodoItemParams {
  todo: Todo;
  projects: Project[];
  onUpdate: (todoId: string, updates: TodoUpdate) => void;
}

export function useTodoItem({ todo, projects, onUpdate }: UseTodoItemParams) {
  const handleToggleComplete = (e: React.ChangeEvent<HTMLInputElement>) => {
    e.stopPropagation();
    const newCompletedState = !todo.completed;

    onUpdate(todo.id, { completed: newCompletedState });
  };

  const user = useCurrentUser();
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

  const checkboxColor = todo.completed
    ? "default"
    : priorityColors[todo.priority];
  const checkboxWrapperClassName = `mt-1 ${todo.completed ? "" : `${priorityRingColors[todo.priority]} border-dashed! border-1 before:border-0! bg-zinc-900`}`;
  const titleClassName = `text-base font-normal ${
    todo.completed ? "text-zinc-500 line-through" : ""
  }`;

  return {
    handleToggleComplete,
    scheduledLabel,
    todoProject,
    isOverdue,
    isToday,
    checkboxColor,
    checkboxWrapperClassName,
    titleClassName,
  };
}

"use client";

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
import { Priority, type Project, type Todo } from "@/types/features/todoTypes";
import { formatDate } from "@/utils/date/dateUtils";

interface TodoItemMetaProps {
  todo: Todo;
  todoProject: Project | undefined;
  scheduledLabel: string | undefined;
  isToday: boolean;
  isOverdue: boolean;
}

const PRIORITY_CHIP_CLASS: Record<Priority, string> = {
  [Priority.HIGH]: "text-red-400 bg-red-400/10",
  [Priority.MEDIUM]: "text-yellow-400 bg-yellow-400/10",
  [Priority.LOW]: "text-blue-400 bg-blue-400/10",
  [Priority.NONE]: "text-zinc-500",
};

const todoHasMeta = (todo: Todo): boolean =>
  todo.priority !== Priority.NONE ||
  !!todo.due_date ||
  !!todo.scheduled_at ||
  !!todo.expires_at ||
  !!todo.vfs_path ||
  todo.labels.length > 0;

const dueChipColor = (isToday: boolean, isOverdue: boolean) => {
  if (isToday) return "success";
  return isOverdue ? "danger" : "default";
};

const capitalize = (value: string) =>
  value.charAt(0).toUpperCase() + value.slice(1);

function TodoPriorityChip({ priority }: { priority: Todo["priority"] }) {
  if (!priority || priority === Priority.NONE) return null;
  return (
    <div className="flex items-center gap-1">
      <Chip
        size="sm"
        variant="flat"
        radius="sm"
        className={`px-2 ${PRIORITY_CHIP_CLASS[priority]}`}
        startContent={<Flag02Icon width={15} height={15} className="mx-1" />}
      >
        {capitalize(priority)}
      </Chip>
    </div>
  );
}

// Chips describing a todo's due date, schedule, project, labels and priority.
export function TodoItemMeta({
  todo,
  todoProject,
  scheduledLabel,
  isToday,
  isOverdue,
}: TodoItemMetaProps) {
  if (!todoHasMeta(todo)) return null;

  return (
    <div className="mt-2 flex flex-wrap items-center gap-1">
      {todo.due_date && (
        <Chip
          className="flex items-center text-zinc-400 px-1"
          size="sm"
          radius="sm"
          color={dueChipColor(isToday, isOverdue)}
          variant="flat"
          startContent={
            <CalendarCheckOut01Icon width={16} height={16} className="mx-1" />
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
          startContent={<Clock01Icon width={16} height={16} className="mx-1" />}
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
          startContent={<AiBrainIcon width={14} height={14} className="mx-1" />}
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
            startContent={<Tag01Icon width={17} height={17} className="mx-1" />}
          >
            {capitalize(label)}
          </Chip>
        ))}
      </div>

      <TodoPriorityChip priority={todo.priority} />

      {/* Subtasks Count */}
      {todo.subtasks.length > 0 && (
        <Chip
          size="sm"
          variant="flat"
          className=" text-zinc-400 px-1"
          radius="sm"
          startContent={
            <CheckmarkCircle02Icon width={15} height={15} className="mx-1" />
          }
        >
          {todo.subtasks.filter((s) => s.completed).length}/
          {todo.subtasks.length} subtasks
        </Chip>
      )}
    </div>
  );
}

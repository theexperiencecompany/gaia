"use client";

import { Chip } from "@heroui/chip";
import {
  AlertCircleIcon,
  CalendarCheckOut01Icon,
  CheckmarkCircle02Icon,
  Clock01Icon,
  Flag02Icon,
  Folder02Icon,
  Tag01Icon,
} from "@icons";
import { formatDistanceToNow } from "date-fns";
import type { ReactNode } from "react";

import { Priority, type Project, type Todo } from "@/types/features/todoTypes";
import { formatDate } from "@/utils/date/dateUtils";

import { INTERNAL_LABELS } from "../constants";
import { GaiaTodoBadge } from "./shared/GaiaTodoBadge";

interface TodoItemChipsProps {
  todo: Todo;
  todoProject: Project | undefined;
  scheduledLabel: string | undefined;
  isToday: boolean;
  isOverdue: boolean;
}

/**
 * The metadata chip row under a todo's title: due date, scheduled time,
 * expiry, goal badge, project, labels, priority and subtask count.
 *
 * Split out of TodoItem because each chip is independently conditional, and
 * eight of them in one row was most of that component's branching — none of
 * which interacts with the row's click or selection behaviour.
 */
export function TodoItemChips({
  todo,
  todoProject,
  scheduledLabel,
  isToday,
  isOverdue,
}: TodoItemChipsProps) {
  return (
    <>
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
              color="default"
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

          {/* Only goals keep an identity chip in the list — for tasks the
                  leading status mark already says GAIA. */}
          {todo.kind === "goal" && (
            <GaiaTodoBadge
              kind={todo.kind}
              assignee={todo.assignee}
              vfsPath={todo.vfs_path}
            />
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
            {todo.labels.reduce<ReactNode[]>((chips, label) => {
              // Internal bookkeeping labels are never shown as chips —
              // "gaia-tracked" is redundant with the "Created by GAIA" badge.
              if (INTERNAL_LABELS.has(label)) return chips;
              chips.push(
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
                </Chip>,
              );
              return chips;
            }, [])}
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
                {todo.priority.charAt(0).toUpperCase() + todo.priority.slice(1)}
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
    </>
  );
}

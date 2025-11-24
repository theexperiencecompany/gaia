"use client";

import { Button } from "@heroui/button";
import { Checkbox } from "@heroui/checkbox";
import { Chip } from "@heroui/chip";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/dropdown";
import { format } from "date-fns";

import { Delete02Icon, MoreVerticalIcon, PencilEdit01Icon } from "@/icons";
import { CalendarIcon } from "@/icons";
import { posthog } from "@/lib";
import { Priority, Todo, TodoUpdate } from "@/types/features/todoTypes";

interface TodoItemProps {
  todo: Todo;
  isSelected: boolean;
  onUpdate: (todoId: string, updates: TodoUpdate) => void;
  onDelete: (todoId: string) => void;
  onEdit?: (todo: Todo) => void;
  onClick?: (todo: Todo) => void;
}

const priorityColors = {
  [Priority.HIGH]: "danger",
  [Priority.MEDIUM]: "warning",
  [Priority.LOW]: "primary",
  [Priority.NONE]: "default",
} as const;

const priorityRingColors = {
  [Priority.HIGH]: "border-danger-500",
  [Priority.MEDIUM]: "border-warning-500",
  [Priority.LOW]: "border-primary-500",
  [Priority.NONE]: "border-zinc-500",
} as const;

export default function TodoItem({
  todo,
  isSelected,
  onUpdate,
  onDelete,
  onEdit,
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

  return (
    <>
      <div
        className={`pointer-events-auto w-full cursor-pointer rounded-xl bg-content2 p-3 shadow-sm transition-all ${
          isSelected
            ? "bg-primary/5 ring-2 ring-primary"
            : "hover:bg-content2/70"
        } ${todo.completed ? "opacity-30" : ""}`}
        onClick={() => {
          onClick?.(todo);
        }}
      >
        <div className="flex h-full items-center gap-3">
          {/* Complete Checkbox */}
          <div onClick={(e) => e.stopPropagation()}>
            <Checkbox
              isSelected={todo.completed}
              onChange={handleToggleComplete}
              color={priorityColors[todo.priority]}
              radius="full"
              classNames={{
                wrapper: `border-1 ${priorityRingColors[todo.priority]} before:border-0!`,
                base: "opacity",
              }}
            />
          </div>

          <div className="min-w-0 flex-1">
            <div>
              <h4
                className={`text-sm font-medium ${
                  todo.completed ? "text-foreground-500 line-through" : ""
                }`}
              >
                {todo.title}
              </h4>
              {todo.description && (
                <p className="mt-1 text-xs text-foreground-500">
                  {todo.description}
                </p>
              )}
            </div>

            {(todo.priority !== Priority.NONE ||
              todo.due_date ||
              todo.labels.length > 0) && (
              <div className="mt-2 flex flex-wrap items-center gap-2">
                {todo.due_date && (
                  <div
                    className={`flex items-center gap-1 text-xs ${
                      isOverdue ? "text-danger" : "text-foreground-500"
                    }`}
                  >
                    <CalendarIcon width={14} height={14} />
                    {format(new Date(todo.due_date), "MMM d")}
                  </div>
                )}

                <div className="flex items-center gap-1">
                  {todo.labels.map((label) => (
                    <Chip key={label} size="sm" variant="flat">
                      {label.charAt(0).toUpperCase() + label.slice(1)}
                    </Chip>
                  ))}
                </div>

                {/* Subtasks Count */}
                {todo.subtasks.length > 0 && (
                  <Chip size="sm" variant="flat" className="text-xs">
                    {todo.subtasks.filter((s) => s.completed).length}/
                    {todo.subtasks.length} subtasks
                  </Chip>
                )}
              </div>
            )}
          </div>

          {/* Actions Menu */}
          <div
            onClick={(e) => e.stopPropagation()}
            className="flex h-full justify-start"
          >
            <Dropdown>
              <DropdownTrigger>
                <Button isIconOnly size="sm" variant="light">
                  <MoreVerticalIcon className="h-4 w-4" />
                </Button>
              </DropdownTrigger>
              <DropdownMenu aria-label="Todo actions">
                <DropdownItem
                  key="edit"
                  startContent={<PencilEdit01Icon className="h-4 w-4" />}
                  onPress={() => onEdit?.(todo)}
                >
                  Edit
                </DropdownItem>
                <DropdownItem
                  key="delete"
                  startContent={<Delete02Icon className="h-4 w-4" />}
                  className="text-danger"
                  color="danger"
                  onPress={() => {
                    // Track todo deletion
                    posthog.capture("todos:deleted", {
                      todo_id: todo.id,
                      was_completed: todo.completed,
                      priority: todo.priority,
                      had_due_date: !!todo.due_date,
                    });
                    onDelete(todo.id);
                  }}
                >
                  Delete
                </DropdownItem>
              </DropdownMenu>
            </Dropdown>
          </div>
        </div>
      </div>
    </>
  );
}

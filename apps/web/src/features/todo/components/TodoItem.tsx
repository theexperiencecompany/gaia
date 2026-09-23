"use client";

import { Checkbox } from "@heroui/checkbox";
import { memo } from "react";
import { ChevronRight } from "@/components/shared/icons";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useTodoItem } from "@/features/todo/hooks/useTodoItem";
import { cn } from "@/lib/utils";
import type { Project, Todo, TodoUpdate } from "@/types/features/todoTypes";
import { Priority } from "@/types/features/todoTypes";
import { TodoItemMeta } from "./TodoItemMeta";
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
  const {
    handleToggleComplete,
    scheduledLabel,
    todoProject,
    isOverdue,
    isToday,
    checkboxColor,
    titleClassName,
  } = useTodoItem({ todo, projects, onUpdate });

  return (
    <div
      className={cn(
        "pointer-events-auto relative w-full rounded-xl p-2 pl-3 mb-0 group todo-item-cv",
        isSelected ? "bg-zinc-800/50" : "hover:bg-zinc-800/50",
        todo.completed && "opacity-30",
        className,
      )}
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
            color={checkboxColor}
            radius="full"
            classNames={{
              wrapper: todo.completed
                ? "mt-1"
                : todo.priority === Priority.HIGH
                  ? "mt-1 border-red-500 border-dashed! border-1 before:border-0! bg-zinc-900"
                  : todo.priority === Priority.MEDIUM
                    ? "mt-1 border-yellow-500 border-dashed! border-1 before:border-0! bg-zinc-900"
                    : todo.priority === Priority.LOW
                      ? "mt-1 border-blue-500 border-dashed! border-1 before:border-0! bg-zinc-900"
                      : "mt-1 border-zinc-500 border-dashed! border-1 before:border-0! bg-zinc-900",
              label: "w-[30vw]",
            }}
          />
        </div>

        <div className="min-w-0 flex-1">
          <div>
            <h4 className={cn("line-clamp-2", titleClassName)}>
              <TodoTitle title={todo.title} />
            </h4>
            {todo.description && (
              <p className="mt-1 text-xs text-zinc-500 line-clamp-1">
                {todo.description}
              </p>
            )}
          </div>

          <TodoItemMeta
            todo={todo}
            todoProject={todoProject}
            scheduledLabel={scheduledLabel}
            isToday={isToday}
            isOverdue={isOverdue}
          />
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

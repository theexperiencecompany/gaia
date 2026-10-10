"use client";

import { Button } from "@heroui/button";
import { Delete02Icon } from "@icons";
import { isTrackedTodo } from "@shared/todos";
import { formatDistanceToNow } from "date-fns";
import type React from "react";
import { SidebarContent, SidebarFooter } from "@/components/ui/sidebar";
import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import CanvasViewer from "@/features/todo/components/CanvasViewer";
import SubtaskManager from "@/features/todo/components/shared/SubtaskManager";
import TodoFieldsRow from "@/features/todo/components/shared/TodoFieldsRow";
import {
  TodoSidebarDescription,
  TodoSidebarTitle,
} from "@/features/todo/components/TodoSidebarEditors";
import WorkflowSection from "@/features/todo/components/WorkflowSection";
import { useTodoSidebar } from "@/features/todo/hooks/useTodoSidebar";
import type {
  Priority,
  Project,
  Todo,
  TodoUpdate,
} from "@/types/features/todoTypes";

interface TodoSidebarProps {
  todo: Todo | null;
  onUpdate: (todoId: string, updates: TodoUpdate) => void;
  onDelete: (todoId: string) => void;
  projects: Project[];
}

export const TodoSidebar: React.FC<TodoSidebarProps> = ({
  todo,
  onUpdate,
  onDelete,
  projects,
}) => {
  const user = useCurrentUser();
  const {
    handleToggleComplete,
    handleDelete,
    handleSubtasksChange,
    handleTitleSave,
    handleDescriptionSave,
    handleFieldChange,
    handleWorkflowLinked,
  } = useTodoSidebar({ todo, onUpdate, onDelete });
  const userTimezone = user?.timezone;

  if (!todo) return null;

  return (
    <div className="flex h-full flex-col">
      <SidebarContent className="flex-1 overflow-y-auto pl-6 pr-3 outline-0">
        <div className="space-y-4 pt-4">
          <TodoSidebarTitle
            title={todo.title}
            completed={todo.completed}
            onToggleComplete={handleToggleComplete}
            onSave={handleTitleSave}
          />
          <TodoSidebarDescription
            description={todo.description}
            completed={todo.completed}
            onSave={handleDescriptionSave}
          />

          {/* Canvas working memory — only for gaia-tracked todos */}
          {isTrackedTodo(todo) && (
            <CanvasViewer todoId={todo.id} todoTitle={todo.title} />
          )}

          {/* Editable Fields */}
          <div className="py-2">
            <TodoFieldsRow
              priority={todo.priority}
              projectId={todo.project_id ?? undefined}
              projects={projects}
              dueDate={todo.due_date ?? undefined}
              dueDateTimezone={todo.due_date_timezone ?? undefined}
              labels={todo.labels}
              onPriorityChange={(priority: Priority) =>
                handleFieldChange("priority", priority)
              }
              onProjectChange={(projectId: string | undefined) =>
                handleFieldChange("project_id", projectId)
              }
              onDateChange={(date: string | undefined, timezone?: string) => {
                handleFieldChange("due_date", date);
                if (timezone) handleFieldChange("due_date_timezone", timezone);
              }}
              onLabelsChange={(labels: string[]) =>
                handleFieldChange("labels", labels)
              }
              userTimezone={userTimezone}
            />
          </div>

          <div
            className={`py-4 border-y-1 border-zinc-800 ${todo?.subtasks?.length > 0 ? "pt-6r" : ""}`}
          >
            <SubtaskManager
              subtasks={todo.subtasks}
              onSubtasksChange={handleSubtasksChange}
            />
          </div>

          {/* Tracked todos run on the agent from their canvas, never a workflow */}
          {!isTrackedTodo(todo) && (
            <WorkflowSection
              key={todo.id}
              hideBg={true}
              todoId={todo.id}
              onWorkflowLinked={handleWorkflowLinked}
            />
          )}
        </div>
      </SidebarContent>

      <SidebarFooter className="p-3">
        <div className="flex items-center justify-between">
          <div className="py-2">
            <span className="text-xs text-zinc-600">
              Created{" "}
              {formatDistanceToNow(new Date(todo.created_at), {
                addSuffix: true,
              })}
            </span>
          </div>

          <Button
            type="button"
            isIconOnly
            color="danger"
            size="sm"
            variant="flat"
            onPress={handleDelete}
            aria-label="Delete todo"
          >
            <Delete02Icon className="size-5" />
          </Button>
        </div>
      </SidebarFooter>
    </div>
  );
};

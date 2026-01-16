"use client";

import { Button } from "@heroui/button";
import { Checkbox } from "@heroui/checkbox";
import { Input, Textarea } from "@heroui/input";
import { formatDistanceToNow } from "date-fns";
import type React from "react";
import { useState } from "react";

import { SidebarContent, SidebarFooter } from "@/components/ui/sidebar";
import { useUser } from "@/features/auth/hooks/useUser";
import SubtaskManager from "@/features/todo/components/shared/SubtaskManager";
import TodoFieldsRow from "@/features/todo/components/shared/TodoFieldsRow";
import WorkflowSection from "@/features/todo/components/WorkflowSection";
import { Delete02Icon } from "@/icons";
import type {
  Priority,
  Project,
  SubTask,
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
  const user = useUser();
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [isEditingDescription, setIsEditingDescription] = useState(false);

  const userTimezone = user?.timezone;

  const handleToggleComplete = () => {
    if (!todo) return;
    onUpdate(todo.id, { completed: !todo.completed });
  };

  const handleDelete = () => {
    if (!todo) return;
    onDelete(todo.id);
  };

  const handleSubtasksChange = (subtasks: SubTask[]) => {
    if (!todo) return;
    onUpdate(todo.id, { subtasks });
  };

  const handleTitleSave = (newTitle: string) => {
    if (!todo) return;
    if (newTitle.trim() && newTitle !== todo.title) {
      onUpdate(todo.id, { title: newTitle.trim() });
    }
    setIsEditingTitle(false);
  };

  const handleDescriptionSave = (newDescription: string) => {
    if (!todo) return;
    if (newDescription !== todo.description) {
      onUpdate(todo.id, { description: newDescription });
    }
    setIsEditingDescription(false);
  };

  const handleFieldChange = (
    field: keyof TodoUpdate,
    value: string | string[] | Priority | undefined,
  ) => {
    if (!todo) return;
    onUpdate(todo.id, { [field]: value } as TodoUpdate);
  };

  // Called when WorkflowSection generates/links a workflow
  const handleWorkflowLinked = (workflowId: string) => {
    if (!todo) return;
    onUpdate(todo.id, { workflow_id: workflowId });
  };

  if (!todo) return null;

  return (
    <div className="flex h-full flex-col">
      <SidebarContent className="flex-1 overflow-y-auto pl-6 pr-3 outline-0">
        <div className="space-y-4 pt-4">
          {/* Title and Description Section */}
          <div className="flex items-start gap-1">
            <Checkbox
              isSelected={todo.completed}
              onValueChange={handleToggleComplete}
              size="lg"
              color="success"
              radius="full"
              classNames={{
                wrapper: `mt-1 ${todo.completed ? "" : "border-foreground-500 border-dashed! border-1 before:border-0! bg-surface-100 "}`,
                label: "w-[30vw]",
              }}
            />
            <div className="flex-1 space-y-3">
              {/* Editable Title */}
              {isEditingTitle ? (
                <Input
                  defaultValue={todo.title}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      handleTitleSave(e.currentTarget.value);
                    }
                    if (e.key === "Escape") {
                      setIsEditingTitle(false);
                    }
                  }}
                  onBlur={(e) => handleTitleSave(e.target.value)}
                  autoFocus
                  classNames={{
                    input:
                      "text-2xl font-medium bg-transparent text-foreground-900 placeholder:text-foreground-500",
                    inputWrapper:
                      "bg-transparent shadow-none hover:bg-transparent focus:bg-transparent data-[focus=true]:bg-transparent",
                  }}
                  variant="underlined"
                />
              ) : (
                <h1
                  onClick={() => setIsEditingTitle(true)}
                  className={`cursor-pointer text-2xl leading-tight font-medium transition-colors hover:text-foreground-800 ${
                    todo.completed
                      ? "text-foreground-500 line-through"
                      : "text-foreground-900"
                  }`}
                >
                  {todo.title}
                </h1>
              )}
            </div>
          </div>

          {isEditingDescription ? (
            <Textarea
              defaultValue={todo.description || ""}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  setIsEditingDescription(false);
                }
              }}
              onBlur={(e) => handleDescriptionSave(e.target.value)}
              placeholder="Add a description..."
              minRows={4}
              maxRows={6}
              autoFocus
              classNames={{
                input: "bg-transparent text-foreground-800 placeholder:text-foreground-500",
                inputWrapper:
                  "bg-surface-200/30 hover:bg-surface-200/50 data-[hover=true]:bg-surface-200/50 shadow-none",
              }}
              variant="flat"
            />
          ) : (
            <p
              onClick={() => setIsEditingDescription(true)}
              className={`cursor-pointer text-sm leading-relaxed transition-colors hover:text-foreground-700 ${
                todo.completed ? "text-foreground-600" : "text-foreground-400"
              }`}
            >
              {todo.description || "Add a description..."}
            </p>
          )}

          {/* Editable Fields */}
          <div className="py-2">
            <TodoFieldsRow
              priority={todo.priority}
              projectId={todo.project_id}
              projects={projects}
              dueDate={todo.due_date}
              dueDateTimezone={todo.due_date_timezone}
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
            className={`py-4 border-y-1 border-surface-200 ${todo?.subtasks?.length > 0 ? "pt-6r" : ""}`}
          >
            <SubtaskManager
              subtasks={todo.subtasks}
              onSubtasksChange={handleSubtasksChange}
            />
          </div>

          <WorkflowSection
            hideBg={true}
            todoId={todo.id}
            onWorkflowLinked={handleWorkflowLinked}
          />
        </div>
      </SidebarContent>

      <SidebarFooter className="p-3">
        <div className="flex items-center justify-between">
          <div className="py-2">
            <span className="text-xs text-foreground-600">
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

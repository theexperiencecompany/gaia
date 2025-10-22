"use client";

import { Input, Textarea } from "@heroui/input";
import { formatDistanceToNow } from "date-fns";
import { Check, Trash2 } from "lucide-react";
import React, { useEffect, useState } from "react";
import { toast } from "sonner";

import { Cancel01Icon } from "@/components/shared/icons";
import {
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
} from "@/components/ui/shadcn/sidebar";
import { useUser } from "@/features/auth/hooks/useUser";
import { todoApi } from "@/features/todo/api/todoApi";
import {
  Priority,
  Project,
  SubTask,
  Todo,
  TodoUpdate,
} from "@/types/features/todoTypes";
import type { Workflow } from "@/types/features/workflowTypes";

import SubtaskManager from "./shared/SubtaskManager";
import TodoFieldsRow from "./shared/TodoFieldsRow";
import WorkflowSection from "./WorkflowSection";

interface TodoSidebarProps {
  todo: Todo | null;
  onClose: () => void;
  onUpdate: (todoId: string, updates: TodoUpdate) => void;
  onDelete: (todoId: string) => void;
  projects: Project[];
}

export const TodoSidebar: React.FC<TodoSidebarProps> = ({
  todo,
  onClose,
  onUpdate,
  onDelete,
  projects,
}) => {
  const user = useUser();
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [isEditingDescription, setIsEditingDescription] = useState(false);
  const [isGeneratingWorkflow, setIsGeneratingWorkflow] = useState(false);
  const [newGeneratedWorkflow, setNewGeneratedWorkflow] = useState<
    Workflow | undefined
  >();

  const userTimezone = user?.timezone;

  // Reset generated workflow when todo changes
  useEffect(() => {
    setNewGeneratedWorkflow(undefined);
  }, [todo?.id]);

  const handleToggleComplete = () => {
    if (!todo) return;
    try {
      onUpdate(todo.id, { completed: !todo.completed });
    } catch (error) {
      console.error("Failed to update todo:", error);
    }
  };

  const handleDelete = () => {
    if (!todo) return;
    onDelete(todo.id);
    onClose();
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

  const handleGenerateWorkflow = async () => {
    if (!todo) return;
    setIsGeneratingWorkflow(true);
    try {
      const result = await todoApi.generateWorkflow(todo.id);
      if (result.workflow) {
        onUpdate(todo.id, { workflow_id: result.workflow.id });
        setNewGeneratedWorkflow(result.workflow);
        toast.success("Workflow generated successfully!");
      }
    } catch (error) {
      console.error("Failed to generate workflow:", error);
      toast.error("Failed to generate workflow");
    } finally {
      setIsGeneratingWorkflow(false);
    }
  };

  const handleWorkflowGenerated = () => {
    if (!todo) return;
    setNewGeneratedWorkflow(undefined);
    toast.success("Workflow updated successfully!");
  };

  if (!todo) return null;

  return (
    <div className="flex h-full flex-col">
      <SidebarHeader className="flex w-full items-end justify-end px-6 pt-4 pb-0">
        <button
          onClick={onClose}
          className="cursor-pointer rounded-lg p-2 text-zinc-400 transition-colors hover:bg-zinc-800/50 hover:text-zinc-200"
          aria-label="Close"
        >
          <Cancel01Icon className="size-4" />
        </button>
      </SidebarHeader>

      <SidebarContent className="flex-1 overflow-y-auto px-6">
        <div className="space-y-4 pt-4">
          {/* Title and Description Section */}
          <div className="flex items-start gap-4">
            <button
              onClick={handleToggleComplete}
              className={`mt-1 flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full transition-all duration-200 ${
                todo.completed
                  ? "bg-green-500"
                  : "border border-zinc-500 hover:border-zinc-400 hover:bg-zinc-800"
              }`}
            >
              {todo.completed && <Check className="h-3 w-3 text-white" />}
            </button>
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
                      "text-2xl font-medium bg-transparent text-zinc-100 placeholder:text-zinc-500",
                    inputWrapper:
                      "bg-transparent shadow-none hover:bg-transparent focus:bg-transparent data-[focus=true]:bg-transparent",
                  }}
                  variant="underlined"
                />
              ) : (
                <h1
                  onClick={() => setIsEditingTitle(true)}
                  className={`cursor-pointer text-2xl leading-tight font-medium transition-colors hover:text-zinc-200 ${
                    todo.completed
                      ? "text-zinc-500 line-through"
                      : "text-zinc-100"
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
                input: "bg-transparent text-zinc-200 placeholder:text-zinc-500",
                inputWrapper:
                  "bg-zinc-800/30 hover:bg-zinc-800/50 data-[hover=true]:bg-zinc-800/50 shadow-none",
              }}
              variant="flat"
            />
          ) : (
            <p
              onClick={() => setIsEditingDescription(true)}
              className={`cursor-pointer text-sm leading-relaxed transition-colors hover:text-zinc-300 ${
                todo.completed ? "text-zinc-600" : "text-zinc-400"
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
              onPriorityChange={(priority) =>
                handleFieldChange("priority", priority)
              }
              onProjectChange={(projectId) =>
                handleFieldChange("project_id", projectId)
              }
              onDateChange={(date, timezone) => {
                handleFieldChange("due_date", date);
                if (timezone) handleFieldChange("due_date_timezone", timezone);
              }}
              onLabelsChange={(labels) => handleFieldChange("labels", labels)}
              userTimezone={userTimezone}
            />
          </div>

          {/* Subtasks Section */}
          <div className="py-2">
            <SubtaskManager
              subtasks={todo.subtasks}
              onSubtasksChange={handleSubtasksChange}
            />
          </div>

          {/* Workflow Section */}
          <div className="py-2">
            <WorkflowSection
              isGenerating={isGeneratingWorkflow}
              todoId={todo.id}
              onGenerateWorkflow={handleGenerateWorkflow}
              onWorkflowGenerated={handleWorkflowGenerated}
              newWorkflow={newGeneratedWorkflow}
            />
          </div>
        </div>
      </SidebarContent>

      <SidebarFooter className="px-6 py-6">
        <div className="flex items-center justify-between">
          <div className="py-2">
            <span className="text-xs text-zinc-600">
              Created{" "}
              {formatDistanceToNow(new Date(todo.created_at), {
                addSuffix: true,
              })}
            </span>
          </div>

          <button
            onClick={handleDelete}
            className="rounded-lg bg-zinc-800/50 p-2.5 text-red-400 transition-all hover:bg-red-500/10 active:scale-95"
            aria-label="Delete todo"
          >
            <Trash2 className="size-4" />
          </button>
        </div>
      </SidebarFooter>
    </div>
  );
};

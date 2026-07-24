"use client";

import { Button } from "@heroui/button";
import { Checkbox } from "@heroui/checkbox";
import { Input, Textarea } from "@heroui/input";
import { BubbleChatIcon, Delete02Icon } from "@icons";
import { formatDistanceToNow } from "date-fns";
import { useRouter } from "next/navigation";
import type React from "react";
import { useState } from "react";
import { SidebarContent, SidebarFooter } from "@/components/ui/sidebar";
import { useUser } from "@/features/auth/hooks/useUser";
import { ExecutionStatusLine } from "@/features/todo/components/shared/ExecutionStatusLine";
import { GaiaOfferBanner } from "@/features/todo/components/shared/GaiaOfferBanner";
import { GaiaTodoBadge } from "@/features/todo/components/shared/GaiaTodoBadge";
import { GaiaTodoMeta } from "@/features/todo/components/shared/GaiaTodoMeta";
import SubtaskManager from "@/features/todo/components/shared/SubtaskManager";
import { TodoAnswerCard } from "@/features/todo/components/shared/TodoAnswerCard";
import TodoFieldsRow from "@/features/todo/components/shared/TodoFieldsRow";
import { TodoProposalActions } from "@/features/todo/components/shared/TodoProposalActions";
import WorkLogSection from "@/features/todo/components/shared/WorkLogSection";
import WorkflowSection from "@/features/todo/components/WorkflowSection";
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
  const router = useRouter();
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

  // `vfs_path` is kept as a fallback signal during the assignee migration
  // window — older gaia-tracked todos may not have `assignee` backfilled yet.
  const isGaiaTodo = todo.assignee === "gaia" || !!todo.vfs_path;
  const isProposed =
    todo.assignee === "gaia" && todo.execution_status === "proposed";

  return (
    <div className="flex h-full flex-col">
      <SidebarContent className="flex-1 overflow-y-auto pl-6 pr-3 outline-0">
        <div className="space-y-4 pt-4">
          {/* One sentence of lifecycle state for GAIA todos. Proposals and
              blocked runs skip it — their decision card carries the state. */}
          {isGaiaTodo &&
            !isProposed &&
            todo.execution_status !== "needs_you" &&
            (todo.kind === "goal" ? (
              <GaiaTodoBadge
                kind={todo.kind}
                assignee={todo.assignee}
                vfsPath={todo.vfs_path}
                size="md"
              />
            ) : (
              <ExecutionStatusLine status={todo.execution_status} />
            ))}

          {/* Title and Description Section. No completion checkbox on GAIA
              todos: their state belongs to the execution lifecycle, and the
              checkbox would flip `completed` around it. */}
          <div className="flex items-start gap-1">
            {!isGaiaTodo && (
              <Checkbox
                isSelected={todo.completed}
                onValueChange={handleToggleComplete}
                size="lg"
                color="success"
                radius="full"
                classNames={{
                  wrapper: `mt-1 ${todo.completed ? "" : "border-zinc-500 border-dashed! border-1 before:border-0! bg-zinc-900 "}`,
                }}
              />
            )}
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
                  className={`cursor-pointer text-2xl leading-tight font-medium break-words transition-colors hover:text-zinc-200 ${todo.completed ? "text-zinc-500 line-through" : "text-zinc-100"}`}
                >
                  {todo.title}
                </h1>
              )}
              {isGaiaTodo && (
                <GaiaTodoMeta
                  // A goal's `serves` restates its own title ("raising a pre-seed
                  // round" on "Raise a pre-seed round"), so it reads as circular —
                  // only tasks carry a meaningful "because".
                  serves={todo.kind === "goal" ? null : todo.serves}
                  errorMessage={
                    todo.execution_status === "failed"
                      ? todo.error_message
                      : null
                  }
                  todoId={todo.id}
                />
              )}
            </div>
          </div>

          {/* Full-width, out of the checkbox column — same rule as the
              decision cards: offers act at page width, not title width. */}
          {!isGaiaTodo && todo.gaia_offer && !todo.gaia_offer_dismissed && (
            <GaiaOfferBanner todoId={todo.id} offer={todo.gaia_offer} />
          )}

          {/* The decision surface, full-width: the staged work + the tap. */}
          {isProposed && (
            <TodoProposalActions
              todoId={todo.id}
              fallbackPreview={todo.description}
              className="mt-0"
            />
          )}

          {/* Blocked runs get the same treatment: question + answer, one card. */}
          {isGaiaTodo && todo.execution_status === "needs_you" && (
            <TodoAnswerCard todoId={todo.id} question={todo.blocker_question} />
          )}

          {/* Proposals skip the description (the decision card already shows
              it), and GAIA todos never show the empty "Add a description"
              affordance — their descriptions are agent-written. */}
          {isProposed ||
          (isGaiaTodo && !todo.description) ? null : isEditingDescription ? (
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
              className={`cursor-pointer text-sm leading-relaxed transition-colors hover:text-zinc-300 ${todo.completed ? "text-zinc-600" : "text-zinc-400"}`}
            >
              {todo.description || "Add a description..."}
            </p>
          )}

          {/* GAIA's canvas.md — a task's work log, or a goal's strategy doc —
              plus a jump into the chat where the run happened/is happening. */}
          {isGaiaTodo && (
            <div className="flex items-center gap-2">
              <WorkLogSection todoId={todo.id} isGoal={todo.kind === "goal"} />
              {todo.last_run_conversation_id && (
                <Button
                  size="sm"
                  variant="flat"
                  radius="lg"
                  onPress={() =>
                    router.push(`/c/${todo.last_run_conversation_id}`)
                  }
                  startContent={
                    <BubbleChatIcon className="size-4 text-zinc-400" />
                  }
                  className="text-zinc-300"
                >
                  {todo.execution_status === "running" ||
                  todo.execution_status === "queued"
                    ? "View live run"
                    : "View run chat"}
                </Button>
              )}
            </div>
          )}

          {/* Editable fields. */}
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

          {/* Subtasks and workflow generation are user-todo machinery: GAIA
              todos execute through their own facets/work log, so offering
              "Generate Workflow" or a subtask composer on them is noise. */}
          {(!isGaiaTodo || todo.subtasks.length > 0) && (
            <div className="py-4 border-y-1 border-zinc-800">
              <SubtaskManager
                subtasks={todo.subtasks}
                onSubtasksChange={handleSubtasksChange}
              />
            </div>
          )}

          {/* One AI affordance per todo: when GAIA is offering to take the
              whole thing over (gaia_offer), don't also pitch a generated
              workflow — two competing "AI helps" paths read as noise. */}
          {!isGaiaTodo && !todo.gaia_offer && (
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

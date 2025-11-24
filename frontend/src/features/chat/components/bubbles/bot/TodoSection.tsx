"use client";

import { format } from "date-fns";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
import {
  ArrowRight01Icon,
  CalendarIcon,
  CheckmarkCircle02Icon,
  Flag01Icon,
  Folder02Icon,
  GridIcon,
  PlayIcon,
  Tick02Icon,
} from "@/icons";
import type {
  TodoAction,
  TodoItem,
  TodoProject,
  TodoToolStats,
} from "@/types/features/todoToolTypes";
import { Priority } from "@/types/features/todoTypes";

interface TodoSectionProps {
  todos?: TodoItem[];
  projects?: TodoProject[];
  stats?: TodoToolStats;
  action?: TodoAction;
  message?: string;
}

const priorityConfig = {
  [Priority.HIGH]: {
    color: "danger" as const,
    icon: <Flag01Icon className="h-3 w-3" />,
    bgColor: "bg-red-500/10",
    textColor: "text-red-500",
  },
  [Priority.MEDIUM]: {
    color: "warning" as const,
    icon: <Flag01Icon className="h-3 w-3" />,
    bgColor: "bg-yellow-500/10",
    textColor: "text-yellow-500",
  },
  [Priority.LOW]: {
    color: "primary" as const,
    icon: <Flag01Icon className="h-3 w-3" />,
    bgColor: "bg-blue-500/10",
    textColor: "text-blue-500",
  },
  [Priority.NONE]: {
    color: "default" as const,
    icon: null,
    bgColor: "",
    textColor: "text-gray-500",
  },
};

export default function TodoSection({
  todos,
  projects,
  stats,
  action = "list",
  message,
}: TodoSectionProps) {
  const router = useRouter();
  const [expandedTodos, setExpandedTodos] = useState<Set<string>>(new Set());
  const { selectWorkflow } = useWorkflowSelection();

  const toggleTodoExpansion = (todoId: string) => {
    const newExpanded = new Set(expandedTodos);
    if (newExpanded.has(todoId)) {
      newExpanded.delete(todoId);
    } else {
      newExpanded.add(todoId);
    }
    setExpandedTodos(newExpanded);
  };
  const handleRunWorkflow = (todo: TodoItem) => {
    if (!todo.workflow) return;

    try {
      // Convert the todo workflow to the expected format
      const workflowData = {
        id: todo.workflow.id,
        title: `${todo.title} Workflow`,
        description: `Execute workflow for todo: ${todo.title}`,
        steps: todo.workflow.steps.map(
          (step: {
            id: string;
            title: string;
            description: string;
            tool_name: string;
            tool_category: string;
          }) => ({
            id: step.id,
            title: step.title,
            description: step.description,
            tool_name: step.tool_name,
            tool_category: step.tool_category,
          }),
        ),
      };

      // Use selectWorkflow to store and navigate to chat with auto-send
      selectWorkflow(workflowData, { autoSend: true });

      console.log(
        "Todo workflow selected for manual execution in chat with auto-send",
      );
    } catch (error) {
      console.error("Failed to select workflow for execution:", error);
    }
  };

  const formatDueDate = (date: string) => {
    const dueDate = new Date(date);
    const now = new Date();
    const daysDiff = Math.floor(
      (dueDate.getTime() - now.getTime()) / (1000 * 60 * 60 * 24),
    );

    if (daysDiff === 0) return "Today";
    if (daysDiff === 1) return "Tomorrow";
    if (daysDiff === -1) return "Yesterday";
    if (daysDiff > 0 && daysDiff < 7) return format(dueDate, "EEEE");
    return format(dueDate, "MMM d");
  };

  const isOverdue = (date: string) => {
    return (
      new Date(date) < new Date() &&
      !todos?.find((t) => t.due_date === date)?.completed
    );
  };

  // Statistics View
  if (action === "stats" && stats) {
    return (
      <div className="mt-3 w-fit min-w-[400px] rounded-2xl rounded-bl-none bg-zinc-800 p-4">
        <div className="mb-3 text-sm">Task Overview</div>
        <div className="grid grid-cols-3 gap-2">
          <div className="rounded-xl bg-zinc-900 p-3 text-center">
            <p className="text-xl font-semibold text-zinc-100">{stats.total}</p>
            <p className="text-xs text-zinc-500">Total</p>
          </div>
          <div className="rounded-xl bg-zinc-900 p-3 text-center">
            <p className="text-xl font-semibold text-green-500">
              {stats.completed}
            </p>
            <p className="text-xs text-zinc-500">Done</p>
          </div>
          <div className="rounded-xl bg-zinc-900 p-3 text-center">
            <p className="text-xl font-semibold text-yellow-500">
              {stats.pending}
            </p>
            <p className="text-xs text-zinc-500">Pending</p>
          </div>
          {stats.overdue > 0 && (
            <div className="rounded-xl bg-zinc-900 p-3 text-center">
              <p className="text-xl font-semibold text-red-500">
                {stats.overdue}
              </p>
              <p className="text-xs text-zinc-500">Overdue</p>
            </div>
          )}
          {stats.today > 0 && (
            <div className="rounded-xl bg-zinc-900 p-3 text-center">
              <p className="text-xl font-semibold text-blue-500">
                {stats.today}
              </p>
              <p className="text-xs text-zinc-500">Today</p>
            </div>
          )}
          {stats.upcoming > 0 && (
            <div className="rounded-xl bg-zinc-900 p-3 text-center">
              <p className="text-xl font-semibold text-purple-500">
                {stats.upcoming}
              </p>
              <p className="text-xs text-zinc-500">Soon</p>
            </div>
          )}
        </div>
      </div>
    );
  }

  // Projects View
  if (projects && projects.length > 0 && !todos) {
    return (
      <div className="mt-3 w-fit min-w-[400px] rounded-2xl rounded-bl-none bg-zinc-800 p-4">
        <div className="mb-3 text-sm">Your Projects</div>
        <div className="space-y-2">
          {projects.map((project) => (
            <div
              key={project.id}
              className="flex cursor-pointer items-center justify-between rounded-xl bg-zinc-900 p-3 hover:bg-zinc-900/70"
              onClick={() => router.push(`/todos/project/${project.id}`)}
            >
              <div className="flex items-center gap-3">
                {project.color && (
                  <div
                    className="h-3 w-3 rounded-full"
                    style={{ backgroundColor: project.color }}
                  />
                )}
                <span className="text-sm font-medium text-zinc-100">
                  {project.name}
                </span>
              </div>
              <div className="flex items-center gap-2 text-xs text-zinc-500">
                {project.todo_count !== undefined && (
                  <span>{project.todo_count} tasks</span>
                )}
                {project.completion_percentage !== undefined && (
                  <span>• {Math.round(project.completion_percentage)}%</span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  // Todos List View
  if (todos && todos.length > 0) {
    return (
      <div className="mt-3 w-fit min-w-[450px] rounded-2xl rounded-bl-none bg-zinc-800 p-4">
        <div className="mb-3 flex items-center justify-between">
          <div className="text-sm">
            {action === "search"
              ? "search Results"
              : action === "create"
                ? "New Task"
                : action === "update"
                  ? "Updated Tasks"
                  : "Tasks"}
          </div>
          <span className="text-xs text-zinc-500">
            {todos.length} {todos.length === 1 ? "task" : "tasks"}
          </span>
        </div>
        <div className="space-y-2">
          {todos.map((todo) => {
            const isExpanded = expandedTodos.has(todo.id);
            const hasDetails =
              todo.description ||
              (todo.subtasks && todo.subtasks.length > 0) ||
              todo.workflow;

            return (
              <div
                key={todo.id}
                className="cursor-pointer rounded-xl bg-zinc-900 p-3 transition-colors hover:bg-zinc-900/70"
                onClick={() => router.push(`/todos?todoId=${todo.id}`)}
              >
                {/* todo Header */}
                <div className="flex items-start gap-3">
                  <button
                    className={`mt-0.5 flex h-4 w-4 flex-shrink-0 items-center justify-center rounded-full border-2 transition-colors ${
                      todo.completed
                        ? "border-success bg-success"
                        : "border-zinc-600 hover:border-zinc-500"
                    }`}
                    onClick={(e) => e.stopPropagation()}
                  >
                    {todo.completed && (
                      <Tick02Icon className="h-2.5 w-2.5 text-white" />
                    )}
                  </button>

                  <div className="flex-1">
                    <div className="flex items-start justify-between gap-2">
                      <h4
                        className={`text-sm font-medium ${
                          todo.completed
                            ? "text-zinc-500 line-through"
                            : "text-zinc-100"
                        }`}
                      >
                        {todo.title}
                      </h4>
                      {hasDetails && (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleTodoExpansion(todo.id);
                          }}
                          className="rounded p-1 hover:bg-zinc-900/70"
                        >
                          <ArrowRight01Icon
                            className={`h-4 w-4 text-zinc-500 transition-transform ${
                              isExpanded ? "rotate-90" : ""
                            }`}
                          />
                        </button>
                      )}
                    </div>

                    {/* todo Metadata */}
                    <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                      {todo.priority !== Priority.NONE && (
                        <span
                          className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-xs ${priorityConfig[todo.priority].bgColor} ${priorityConfig[todo.priority].textColor}`}
                        >
                          {priorityConfig[todo.priority].icon}
                          {todo.priority}
                        </span>
                      )}

                      {todo.due_date && (
                        <span
                          className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-xs ${
                            isOverdue(todo.due_date)
                              ? "bg-red-500/10 text-red-500"
                              : "bg-zinc-800 text-zinc-400"
                          }`}
                        >
                          <CalendarIcon className="h-3 w-3" />
                          {formatDueDate(todo.due_date)}
                        </span>
                      )}

                      {todo.project && (
                        <span className="flex items-center gap-1 rounded-full bg-zinc-800 px-2 py-0.5 text-xs text-zinc-400">
                          {todo.project.color ? (
                            <div
                              className="h-2 w-2 rounded-full"
                              style={{
                                backgroundColor: todo.project.color,
                              }}
                            />
                          ) : (
                            <Folder02Icon className="h-3 w-3" />
                          )}
                          {todo.project.name}
                        </span>
                      )}

                      {todo.labels.map((label) => (
                        <span
                          key={label}
                          className="flex items-center gap-1 rounded-full bg-zinc-800 px-2 py-0.5 text-xs text-zinc-400"
                        >
                          <GridIcon className="h-3 w-3" />
                          {label}
                        </span>
                      ))}

                      {todo.subtasks && todo.subtasks.length > 0 && (
                        <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-xs text-zinc-400">
                          {todo.subtasks.filter((s) => s.completed).length}/
                          {todo.subtasks.length} subtasks
                        </span>
                      )}
                    </div>

                    {/* Expanded Content */}
                    {isExpanded && (
                      <div className="mt-3 space-y-3">
                        {todo.description && (
                          <p className="text-sm text-zinc-400">
                            {todo.description}
                          </p>
                        )}

                        {todo.subtasks && todo.subtasks.length > 0 && (
                          <div className="space-y-1">
                            <p className="text-xs font-medium text-zinc-500">
                              Subtasks
                            </p>
                            {todo.subtasks.map((subtask) => (
                              <div
                                key={subtask.id}
                                className="flex items-center gap-2 pl-2"
                                onClick={(e) => e.stopPropagation()}
                              >
                                <div
                                  className={`flex h-4 w-4 items-center justify-center rounded-full border-2 ${
                                    subtask.completed
                                      ? "border-success bg-success"
                                      : "border-zinc-600"
                                  }`}
                                >
                                  {subtask.completed && (
                                    <Tick02Icon className="h-2.5 w-2.5 text-white" />
                                  )}
                                </div>
                                <span
                                  className={`text-xs ${
                                    subtask.completed
                                      ? "text-zinc-500 line-through"
                                      : "text-zinc-300"
                                  }`}
                                >
                                  {subtask.title}
                                </span>
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Workflow Section */}
                        {todo.workflow && (
                          <div className="space-y-2">
                            <p className="text-xs font-medium text-zinc-500">
                              Workflow ({todo.workflow.steps.length} steps)
                            </p>
                            <Button
                              size="sm"
                              variant="outline"
                              className="h-7 border-green-500/30 bg-green-500/20 text-green-400 hover:bg-green-500/30"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleRunWorkflow(todo);
                              }}
                            >
                              <PlayIcon className="mr-1 h-3 w-3" />
                              Run Workflow
                            </Button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
        {message && <p className="mt-3 text-xs text-zinc-500">{message}</p>}
      </div>
    );
  }

  // Empty State
  if (action === "list" && (!todos || todos.length === 0)) {
    return (
      <div className="mt-3 w-fit min-w-[300px] rounded-2xl rounded-bl-none bg-zinc-800 p-6 text-center">
        <CheckmarkCircle02Icon className="mx-auto h-8 w-8 text-zinc-600" />
        <p className="mt-2 text-sm text-zinc-300">No tasks found</p>
        {message && <p className="mt-1 text-xs text-zinc-500">{message}</p>}
      </div>
    );
  }

  // Success/Action Message
  if (message && !todos && !stats && !projects) {
    const isDeleteAction = action === "delete";
    const iconColor = isDeleteAction ? "text-red-500" : "text-green-500";

    return (
      <div className="mt-3 w-fit rounded-2xl rounded-bl-none bg-zinc-800 p-4">
        <div className="flex items-center gap-2">
          <CheckmarkCircle02Icon className={`h-4 w-4 ${iconColor}`} />
          <p className="text-sm">{message}</p>
        </div>
      </div>
    );
  }

  return null;
}

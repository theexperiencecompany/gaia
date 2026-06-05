"use client";

import { ScrollShadow } from "@heroui/scroll-shadow";
import { CheckmarkCircle02Icon } from "@icons";
import { useRouter } from "next/navigation";
import TodoItem from "@/features/todo/components/TodoItem";
import { useTodoStore } from "@/stores/todoStore";
import type {
  TodoItem as ChatTodoItem,
  TodoProject as ChatTodoProject,
  TodoAction,
  TodoToolStats,
} from "@/types/features/todoToolTypes";
import type { Project, Todo } from "@/types/features/todoTypes";

interface TodoSectionProps {
  todos?: ChatTodoItem[];
  projects?: ChatTodoProject[];
  stats?: TodoToolStats;
  action?: TodoAction;
  message?: string;
}

// Adapt the streamed chat task payload to the canonical task model the shared
// TodoItem component (used on the todos page) expects, so chat and page render
// identically and can never drift. Missing optional fields (scheduled_at,
// vfs_path, etc.) are simply absent — TodoItem renders them conditionally.
function toCanonicalTodo(t: ChatTodoItem): Todo {
  return {
    id: t.id,
    user_id: "",
    title: t.title,
    description: t.description,
    labels: t.labels ?? [],
    due_date: t.due_date,
    due_date_timezone: t.due_date_timezone,
    priority: t.priority,
    project_id: t.project_id ?? "",
    completed: t.completed,
    subtasks: (t.subtasks ?? []).map((s) => ({
      id: s.id,
      title: s.title,
      completed: s.completed,
      created_at: t.created_at,
    })),
    workflow_id: t.workflow?.id,
    created_at: t.created_at,
    updated_at: t.updated_at,
  };
}

function toCanonicalProject(p: ChatTodoProject): Project {
  return {
    id: p.id,
    user_id: "",
    name: p.name,
    description: p.description,
    color: p.color,
    is_default: p.is_default ?? false,
    todo_count: p.todo_count ?? 0,
    created_at: "",
    updated_at: "",
  };
}

export default function TodoSection({
  todos,
  projects,
  stats,
  action = "list",
  message,
}: TodoSectionProps) {
  const router = useRouter();
  const updateTodo = useTodoStore((s) => s.updateTodo);

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

  // Todos List View — reuse the canonical todos-page TodoItem. No card chrome:
  // just the rows, clicking opens the task on the todos page.
  if (todos && todos.length > 0) {
    // Build the projects lookup TodoItem needs from the streamed projects plus
    // any project embedded inline on a task.
    const projectMap = new Map<string, Project>();
    for (const p of projects ?? []) projectMap.set(p.id, toCanonicalProject(p));
    for (const t of todos) {
      if (t.project && !projectMap.has(t.project.id)) {
        projectMap.set(t.project.id, toCanonicalProject(t.project));
      }
    }
    const projectList = Array.from(projectMap.values());

    return (
      <ScrollShadow className="mt-3 flex max-h-[400px] w-full max-w-xl flex-col gap-2">
        {todos.map((todo) => (
          <TodoItem
            key={todo.id}
            todo={toCanonicalTodo(todo)}
            projects={projectList}
            isSelected={false}
            onUpdate={(todoId, updates) => updateTodo(todoId, updates)}
            onClick={(t) => router.push(`/todos?todoId=${t.id}`)}
            className="rounded-2xl bg-zinc-800 hover:bg-zinc-800/80"
          />
        ))}
      </ScrollShadow>
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

  // Success/Action Message (delete confirmations etc. that return no task rows)
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

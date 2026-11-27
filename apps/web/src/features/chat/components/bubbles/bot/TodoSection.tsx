"use client";

import { ScrollShadow } from "@heroui/react";
import { CheckmarkCircle02Icon } from "@icons";
import type {
  ProjectResponse,
  TodoResponse,
  TodoStats,
} from "@shared/api/generated";
import { useRouter } from "next/navigation";
import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import TodoItem from "@/features/todo/components/TodoItem";
import { useTodoStore } from "@/stores/todoStore";
import type { TodoAction } from "@/types/features/todoToolTypes";
import type { Project, Todo, TodoUpdate } from "@/types/features/todoTypes";

interface TodoSectionProps {
  todos?: TodoResponse[];
  projects?: ProjectResponse[];
  stats?: TodoStats;
  action?: TodoAction;
  message?: string;
}

// TodoItem still takes the hand-written shared Project, not ProjectResponse.
function toCanonicalProject(p: ProjectResponse): Project {
  return {
    id: p.id,
    user_id: p.user_id,
    name: p.name,
    description: p.description ?? undefined,
    color: p.color ?? undefined,
    is_default: p.is_default ?? false,
    todo_count: p.todo_count ?? 0,
    created_at: p.created_at,
    updated_at: p.updated_at,
  };
}

function TodoStatsView({ stats }: { stats: TodoStats }) {
  return (
    <div className="mt-3 w-fit min-w-[400px] rounded-2xl rounded-bl-none bg-zinc-800 p-4">
      <div className="mb-3 text-sm">Task Overview</div>
      <div className="grid grid-cols-3 gap-2">
        <div className="rounded-xl bg-zinc-900 p-3 text-center">
          <p className="text-xl font-semibold text-zinc-100">
            {stats.total ?? 0}
          </p>
          <p className="text-xs text-zinc-500">Total</p>
        </div>
        <div className="rounded-xl bg-zinc-900 p-3 text-center">
          <p className="text-xl font-semibold text-green-500">
            {stats.completed ?? 0}
          </p>
          <p className="text-xs text-zinc-500">Done</p>
        </div>
        <div className="rounded-xl bg-zinc-900 p-3 text-center">
          <p className="text-xl font-semibold text-yellow-500">
            {stats.pending ?? 0}
          </p>
          <p className="text-xs text-zinc-500">Pending</p>
        </div>
        {(stats.overdue ?? 0) > 0 && (
          <div className="rounded-xl bg-zinc-900 p-3 text-center">
            <p className="text-xl font-semibold text-red-500">
              {stats.overdue}
            </p>
            <p className="text-xs text-zinc-500">Overdue</p>
          </div>
        )}
      </div>
    </div>
  );
}

function TodoProjectsView({
  projects,
  onOpenProject,
}: {
  projects: ProjectResponse[];
  onOpenProject: (projectId: string) => void;
}) {
  return (
    <div className="mt-3 w-fit min-w-[400px] rounded-2xl rounded-bl-none bg-zinc-800 p-4">
      <div className="mb-3 text-sm">Your Projects</div>
      <div className="space-y-2">
        {projects.map((project) => (
          <button
            type="button"
            key={project.id}
            className="flex w-full cursor-pointer items-center justify-between rounded-xl bg-zinc-900 p-3 text-left hover:bg-zinc-900/70"
            onClick={() => onOpenProject(project.id)}
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
            </div>
          </button>
        ))}
      </div>
    </div>
  );
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
  const user = useCurrentUser();

  // Statistics View
  if (action === "stats" && stats) {
    return <TodoStatsView stats={stats} />;
  }

  // Projects View
  if (projects && projects.length > 0 && !todos) {
    return (
      <TodoProjectsView
        projects={projects}
        onOpenProject={(projectId) =>
          router.push(`/todos/project/${projectId}`)
        }
      />
    );
  }

  // Todos List View — reuse the canonical todos-page TodoItem. No card chrome:
  // just the rows, clicking opens the task on the todos page.
  if (todos && todos.length > 0) {
    return (
      <TodoSectionList
        todos={todos}
        projects={projects}
        timezone={user?.timezone}
        onUpdateTodo={(todoId, updates) => updateTodo(todoId, updates)}
        onOpenTodo={(t) => router.push(`/todos?todoId=${t.id}`)}
      />
    );
  }

  // Empty State
  if (action === "list" && (!todos || todos.length === 0)) {
    return <TodoSectionEmpty message={message} />;
  }

  // Success/Action Message (delete confirmations etc. that return no task rows)
  if (message && !todos && !stats && !projects) {
    return <TodoSectionMessage action={action} message={message} />;
  }

  return null;
}

function TodoSectionEmpty({ message }: { message: string | undefined }) {
  return (
    <div className="mt-3 w-fit min-w-[300px] rounded-2xl rounded-bl-none bg-zinc-800 p-6 text-center">
      <CheckmarkCircle02Icon className="mx-auto h-8 w-8 text-zinc-600" />
      <p className="mt-2 text-sm text-zinc-300">No tasks found</p>
      {message && <p className="mt-1 text-xs text-zinc-500">{message}</p>}
    </div>
  );
}

function TodoSectionMessage({
  action,
  message,
}: {
  action: TodoAction;
  message: string;
}) {
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

function TodoSectionList({
  todos,
  projects,
  timezone,
  onUpdateTodo,
  onOpenTodo,
}: {
  todos: TodoResponse[];
  projects: ProjectResponse[] | undefined;
  timezone: string | undefined;
  onUpdateTodo: (todoId: string, updates: TodoUpdate) => void;
  onOpenTodo: (todo: Todo) => void;
}) {
  const projectList = (projects ?? []).map(toCanonicalProject);

  return (
    <ScrollShadow className="mt-3 flex max-h-[400px] w-full max-w-xl flex-col gap-2">
      {todos.map((todo) => (
        <TodoItem
          key={todo.id}
          todo={todo}
          projects={projectList}
          isSelected={false}
          onUpdate={onUpdateTodo}
          onClick={onOpenTodo}
          timezone={timezone}
          className="rounded-2xl bg-zinc-800 hover:bg-zinc-800/80"
        />
      ))}
    </ScrollShadow>
  );
}

"use client";

import { Link } from "@heroui/link";
import { Skeleton } from "@heroui/skeleton";
import { AlertCircleIcon, CheckmarkCircle02Icon, Flag02Icon } from "@icons";
import { ExecutionStatusGlyph } from "@/features/todo/components/shared/ExecutionStatusGlyph";
import { TodoProposalActions } from "@/features/todo/components/shared/TodoProposalActions";
import type {
  DashboardTodayItem,
  DashboardTodayResponse,
} from "@/types/features/dashboardTypes";
import type { Todo } from "@/types/features/todoTypes";
import { Priority } from "@/types/features/todoTypes";

const PRIORITY_RANK: Record<Priority, number> = {
  [Priority.HIGH]: 0,
  [Priority.MEDIUM]: 1,
  [Priority.LOW]: 2,
  [Priority.NONE]: 3,
};

function compareByDueDateThenPriority(a: Todo, b: Todo): number {
  if (a.due_date && b.due_date) {
    const dueDiff = a.due_date.localeCompare(b.due_date);
    if (dueDiff !== 0) return dueDiff;
  } else if (a.due_date) {
    return -1;
  } else if (b.due_date) {
    return 1;
  }
  return PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority];
}

interface ActionRailProps {
  todos: Todo[];
  todosLoading: boolean;
  todayData: DashboardTodayResponse | undefined;
}

export function ActionRail({
  todos,
  todosLoading,
  todayData,
}: ActionRailProps) {
  const nextUp = [...todos]
    .filter((t) => t.assignee !== "gaia" && !t.completed)
    .sort(compareByDueDateThenPriority)[0];

  const waitingOnYou = todos.filter(
    (t) =>
      t.execution_status === "proposed" || t.execution_status === "needs_you",
  );

  const doneToday = (todayData?.items ?? []).filter(
    (item): item is DashboardTodayItem & { assignee: "user" | "gaia" } =>
      item.type === "todo" && item.status === "done" && item.assignee != null,
  );
  const gaiaDoneCount = doneToday.filter((i) => i.assignee === "gaia").length;
  const userDoneCount = doneToday.filter((i) => i.assignee === "user").length;

  return (
    <div className="flex flex-col gap-4">
      <section className="rounded-2xl bg-zinc-800 p-4">
        <p className="mb-3 text-sm font-semibold text-zinc-100">Next up</p>
        {todosLoading ? (
          <Skeleton className="h-16 rounded-2xl" />
        ) : nextUp ? (
          <Link
            href={`/todos?todoId=${nextUp.id}`}
            className="block rounded-2xl bg-zinc-900 p-3 transition hover:bg-white/5"
          >
            <p className="truncate text-sm font-medium text-zinc-200">
              {nextUp.title}
            </p>
            {nextUp.due_date && (
              <p className="mt-0.5 text-xs text-zinc-500">
                Due {new Date(nextUp.due_date).toLocaleDateString()}
              </p>
            )}
          </Link>
        ) : (
          <p className="rounded-2xl bg-zinc-900 p-3 text-sm text-zinc-500">
            Nothing queued up — you're clear.
          </p>
        )}
      </section>

      <section className="rounded-2xl bg-zinc-800 p-4">
        <p className="mb-3 text-sm font-semibold text-zinc-100">
          Waiting on you
        </p>
        {todosLoading ? (
          <Skeleton className="h-16 rounded-2xl" />
        ) : waitingOnYou.length === 0 ? (
          <p className="rounded-2xl bg-zinc-900 p-3 text-sm text-zinc-500">
            Nothing needs your review right now.
          </p>
        ) : (
          <div className="space-y-2">
            {waitingOnYou.map((todo) => (
              <div key={todo.id} className="rounded-2xl bg-zinc-900 p-3">
                <p className="truncate text-sm font-medium text-zinc-200">
                  {todo.title}
                </p>
                {todo.serves && (
                  <p className="mt-0.5 line-clamp-1 text-xs text-zinc-500">
                    {todo.serves}
                  </p>
                )}
                <TodoProposalActions
                  todoId={todo.id}
                  fallbackPreview={todo.description}
                />
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="rounded-2xl bg-zinc-800 p-4">
        <p className="mb-3 text-sm font-semibold text-zinc-100">Done today</p>
        <p className="rounded-2xl bg-zinc-900 p-3 text-sm text-zinc-300">
          GAIA {gaiaDoneCount}
          <span className="mx-1 text-zinc-600">·</span>
          You {userDoneCount}
        </p>
      </section>
    </div>
  );
}

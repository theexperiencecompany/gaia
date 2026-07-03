"use client";

import { Link } from "@heroui/link";
import { Skeleton } from "@heroui/skeleton";
import { CheckmarkCircle02Icon, CircleIcon } from "@icons";
import { ExecutionStatusGlyph } from "@/features/todo/components/shared/ExecutionStatusGlyph";
import { cn } from "@/lib/utils";
import type {
  DashboardTodayItem,
  DashboardTodayResponse,
} from "@/types/features/dashboardTypes";
import type { ExecutionStatus } from "@/types/features/todoTypes";

interface TodayTimelineProps {
  data: DashboardTodayResponse | undefined;
  isLoading: boolean;
}

function formatTime(time: string | null): string {
  if (!time) return "";
  const date = new Date(time);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
  });
}

function isKnownExecutionStatus(
  status: string | null | undefined,
): status is ExecutionStatus {
  return (
    status === "proposed" ||
    status === "queued" ||
    status === "running" ||
    status === "needs_you" ||
    status === "done" ||
    status === "failed" ||
    status === "expired" ||
    status === "dismissed"
  );
}

function ItemGlyph({ item }: { item: DashboardTodayItem }) {
  if (item.type === "todo" && isKnownExecutionStatus(item.status)) {
    return <ExecutionStatusGlyph status={item.status} className="mt-0.5" />;
  }

  const isPast = item.time ? new Date(item.time).getTime() < Date.now() : false;
  return isPast ? (
    <CheckmarkCircle02Icon className="mt-0.5 size-4 shrink-0 text-zinc-500" />
  ) : (
    <CircleIcon className="mt-0.5 size-4 shrink-0 text-zinc-600" />
  );
}

function TimelineRow({ item }: { item: DashboardTodayItem }) {
  const content = (
    <div
      className={cn(
        "flex items-start gap-3 rounded-2xl bg-zinc-900 p-3 border-l-2",
        item.assignee === "gaia" ? "border-primary/60" : "border-transparent",
      )}
    >
      <span className="w-14 shrink-0 pt-0.5 text-xs text-zinc-500">
        {formatTime(item.time)}
      </span>
      <ItemGlyph item={item} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-zinc-200">
          {item.title}
        </p>
        {item.subtitle && (
          <p className="mt-0.5 line-clamp-1 text-xs text-zinc-500">
            {item.subtitle}
          </p>
        )}
      </div>
    </div>
  );

  if (item.todo_id) {
    return (
      <Link
        href={`/todos?todoId=${item.todo_id}`}
        className="block transition hover:bg-white/5 rounded-2xl"
      >
        {content}
      </Link>
    );
  }

  return content;
}

export function TodayTimeline({ data, isLoading }: TodayTimelineProps) {
  if (isLoading) {
    return (
      <div className="rounded-2xl bg-zinc-800 p-4 space-y-2">
        <p className="mb-3 text-sm font-semibold text-zinc-100">Today</p>
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton
            key={`today-skeleton-${i + 1}`}
            className="h-14 rounded-2xl"
          />
        ))}
      </div>
    );
  }

  const items = [...(data?.items ?? [])].sort((a, b) =>
    (a.time ?? "9999").localeCompare(b.time ?? "9999"),
  );

  return (
    <div className="rounded-2xl bg-zinc-800 p-4">
      <p className="mb-3 text-sm font-semibold text-zinc-100">Today</p>
      {items.length === 0 ? (
        <p className="rounded-2xl bg-zinc-900 p-4 text-sm text-zinc-500">
          Nothing on the board yet today.
        </p>
      ) : (
        <div className="space-y-2">
          {items.map((item, index) => (
            <TimelineRow
              key={`${item.type}-${item.todo_id ?? item.title}-${index}`}
              item={item}
            />
          ))}
        </div>
      )}
    </div>
  );
}

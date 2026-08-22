"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Skeleton } from "@heroui/skeleton";
import {
  AlertCircleIcon,
  CheckmarkCircle02Icon,
  Clock04Icon,
  Loading03Icon,
} from "@icons";
import { useRouter } from "next/navigation";
import { useLocale } from "next-intl";
import { useMemo } from "react";
import { ChevronRight } from "@/components/shared/icons";

import { useWorkflowExecutions } from "../hooks/useWorkflowExecutions";
import type { WorkflowExecution } from "../types/workflowExecutionTypes";
import PanelHeader from "./workflow-modal/PanelHeader";

interface WorkflowExecutionHistoryProps {
  workflowId: string;
}

/**
 * Human-relative label ("5m ago") for recent timestamps, or null when the
 * timestamp is older than a week and needs a calendar date — the caller then
 * formats it with a locale-aware formatter.
 */
function getRelativeDateLabel(dateString: string): string | null {
  const date = new Date(dateString);
  const now = new Date();
  const diffSecs = Math.floor((now.getTime() - date.getTime()) / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffSecs < 60) return "Just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return `${diffDays}d ago`;
  return null;
}

function formatDuration(seconds: number | undefined): string {
  if (!seconds) return "";
  if (seconds < 60) return `Ran for ${Math.round(seconds)}s`;
  if (seconds < 3600) return `Ran for ${Math.round(seconds / 60)}m`;
  return `Ran for ${Math.round(seconds / 3600)}h`;
}

function ExecutionStatusBadge({
  status,
}: {
  status: WorkflowExecution["status"];
}) {
  switch (status) {
    case "success":
      return (
        <Chip
          size="sm"
          color="success"
          variant="flat"
          radius="sm"
          startContent={<CheckmarkCircle02Icon className="h-3 w-3" />}
        >
          Success
        </Chip>
      );
    case "failed":
      return (
        <Chip
          size="sm"
          color="danger"
          variant="flat"
          radius="sm"
          startContent={<AlertCircleIcon className="h-3 w-3" />}
        >
          Failed
        </Chip>
      );
    case "running":
      return (
        <Chip
          size="sm"
          color="primary"
          radius="sm"
          variant="flat"
          startContent={
            <div className="animate-spin">
              <Loading03Icon className="h-3 w-3" />
            </div>
          }
        >
          Running
        </Chip>
      );
  }
}

function ExecutionItem({ execution }: { execution: WorkflowExecution }) {
  const router = useRouter();
  const locale = useLocale();

  // Calendar fallback for timestamps older than a week. The formatter gets an
  // explicit locale (from the i18n provider, never an ambient runtime default)
  // and is memoized, so the rendered text is identical on server and browser.
  const calendarDateFormat = useMemo(
    () => new Intl.DateTimeFormat(locale, { month: "short", day: "numeric" }),
    [locale],
  );

  const relativeLabel = getRelativeDateLabel(execution.started_at);

  const handleViewClick = () => {
    if (execution.conversation_id) {
      router.push(`/c/${execution.conversation_id}`);
    }
  };

  const isClickable = !!execution.conversation_id;

  return (
    <div
      className={`flex items-center justify-between rounded-2xl bg-zinc-800/50 p-3 transition-colors hover:bg-zinc-800 ${isClickable ? "cursor-pointer" : ""}`}
      onClick={isClickable ? handleViewClick : undefined}
      onKeyDown={
        isClickable
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") handleViewClick();
            }
          : undefined
      }
      role={isClickable ? "button" : undefined}
      tabIndex={isClickable ? 0 : undefined}
    >
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <ExecutionStatusBadge status={execution.status} />
          {execution.duration_seconds && (
            <span className="text-xs text-zinc-500">
              {formatDuration(execution.duration_seconds)}
            </span>
          )}
        </div>
        {execution.summary && (
          <p className="text-xs text-zinc-400 line-clamp-1">
            {execution.summary}
          </p>
        )}
        {execution.error_message && (
          <p className="text-xs text-danger line-clamp-1">
            {execution.error_message}
          </p>
        )}
      </div>
      <div className="flex items-center gap-2">
        <span className="text-xs text-zinc-500">
          {relativeLabel ??
            calendarDateFormat.format(new Date(execution.started_at))}
        </span>
        {isClickable && <ChevronRight className="h-4 w-4 text-zinc-500" />}
      </div>
    </div>
  );
}

export default function WorkflowExecutionHistory({
  workflowId,
}: WorkflowExecutionHistoryProps) {
  const { executions, isLoading, total, hasMore, loadMore } =
    useWorkflowExecutions(workflowId);

  if (isLoading && executions.length === 0) {
    return (
      <div className="space-y-2 mt-7">
        <Skeleton className="h-12 w-full rounded-2xl" />
        <Skeleton className="h-12 w-full rounded-2xl" />
        <Skeleton className="h-12 w-full rounded-2xl" />
        <Skeleton className="h-12 w-full rounded-2xl" />
      </div>
    );
  }

  if (executions.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-8 text-center">
        <div className="mb-3 rounded-full bg-zinc-800/50 p-3">
          <Clock04Icon className="h-5 w-5 text-zinc-500" />
        </div>
        <p className="text-sm text-zinc-400">No executions yet</p>
        <p className="text-xs text-zinc-500">
          Run this workflow to see execution history
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <PanelHeader badge={`${total} runs`} />
      <div className="space-y-2 overflow-y-auto">
        {executions.map((execution) => (
          <ExecutionItem key={execution.execution_id} execution={execution} />
        ))}
      </div>
      {hasMore && (
        <Button
          size="sm"
          variant="flat"
          className="w-full"
          onPress={loadMore}
          isLoading={isLoading}
        >
          Load More
        </Button>
      )}
    </div>
  );
}

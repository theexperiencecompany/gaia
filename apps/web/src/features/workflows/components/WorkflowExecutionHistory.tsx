"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Skeleton } from "@heroui/skeleton";
import { useRouter } from "next/navigation";

import {
  AlertCircleIcon,
  CheckmarkCircle02Icon,
  ChevronRight,
  Clock04Icon,
  Loading03Icon,
} from "@/icons";

import { useWorkflowExecutions } from "../hooks/useWorkflowExecutions";
import type { WorkflowExecution } from "../types/workflowExecutionTypes";
import PanelHeader from "./workflow-modal/PanelHeader";

interface WorkflowExecutionHistoryProps {
  workflowId: string;
}

function formatDuration(seconds: number | undefined): string {
  if (!seconds) return "-";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${Math.round(seconds / 3600)}h`;
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
          variant="flat"
          startContent={<Loading03Icon className="h-3 w-3 animate-spin" />}
        >
          Running
        </Chip>
      );
  }
}

function ExecutionItem({ execution }: { execution: WorkflowExecution }) {
  const router = useRouter();

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
      {isClickable && <ChevronRight className="h-4 w-4 text-zinc-500" />}
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
      <div className="space-y-2">
        <Skeleton className="h-12 w-full rounded-lg" />
        <Skeleton className="h-12 w-full rounded-lg" />
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
      <div className="max-h-64 space-y-2 overflow-y-auto">
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

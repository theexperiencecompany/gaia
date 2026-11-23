"use client";

import { Skeleton } from "@heroui/react";
import { Clock04Icon } from "@icons";
import { formatDuration, formatRelativeDate } from "@shared/utils";
import { useRouter } from "next/navigation";
import { useLocale } from "next-intl";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { ChevronRight } from "@/components/shared/icons";
import { ShareLinkControls } from "@/features/short-links/components/ShareLinkControls";

import { useWorkflowExecutions } from "../hooks/useWorkflowExecutions";
import type { WorkflowExecution } from "../types/workflowExecutionTypes";
import { ExecutionStatusBadge } from "./ExecutionStatusBadge";
import PanelHeader from "./workflow-modal/PanelHeader";

interface WorkflowExecutionHistoryProps {
  workflowId: string;
}

function ExecutionItem({ execution }: { execution: WorkflowExecution }) {
  const router = useRouter();
  const locale = useLocale();

  // The locale comes from the i18n provider, never an ambient runtime default,
  // so the rendered text is identical on server and browser.
  const startedLabel = formatRelativeDate(execution.started_at, { locale });

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
        {/* Two lines: a skip or a quiet-hours run leads with its reason. */}
        {execution.summary && (
          <p className="text-xs text-zinc-400 line-clamp-2">
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
        {execution.status !== "running" && (
          <ShareLinkControls
            iconOnly
            target={{ type: "workflow_run", id: execution.execution_id }}
          />
        )}
        <span className="text-xs text-zinc-500">{startedLabel}</span>
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
        <GaiaButton
          size="sm"
          variant="default-soft"
          className="w-full"
          onPress={loadMore}
          isPending={isLoading}
        >
          Load More
        </GaiaButton>
      )}
    </div>
  );
}

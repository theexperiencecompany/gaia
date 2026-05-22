import type { Workflow } from "../types/workflow";

export const WORKFLOW_STATUS_TTL_MS = 30_000;

/**
 * WebSocket event names emitted by the API for todo-workflow lifecycle.
 * Both web and mobile subscribe to the same events; their socket clients
 * differ but the event keys are identical.
 */
export const WORKFLOW_WS_EVENTS = {
  WORKFLOW_GENERATED: "workflow.generated",
  WORKFLOW_GENERATION_STARTED: "workflow.generation_started",
  WORKFLOW_GENERATION_FAILED: "workflow.generation_failed",
} as const;

export interface WorkflowStatusCacheEntry {
  has_workflow: boolean;
  is_generating: boolean;
  workflow: Workflow | null;
  cachedAt: number;
}

export function isWorkflowStatusFresh(
  entry: WorkflowStatusCacheEntry | undefined,
  now: number = Date.now(),
  ttlMs: number = WORKFLOW_STATUS_TTL_MS,
): entry is WorkflowStatusCacheEntry {
  if (!entry) return false;
  return now - entry.cachedAt < ttlMs;
}

export function buildWorkflowStatusEntry(
  status: {
    has_workflow: boolean;
    is_generating: boolean;
    workflow: Workflow | null;
  },
  now: number = Date.now(),
): WorkflowStatusCacheEntry {
  return {
    has_workflow: status.has_workflow,
    is_generating: status.is_generating,
    workflow: status.workflow,
    cachedAt: now,
  };
}

import { useCallback, useEffect, useRef, useState } from "react";
import { wsManager } from "@/lib/websocket-client";
import { WS_EVENTS } from "@/lib/websocket-events";
import { workflowApi } from "../api/workflow-api";
import type { WorkflowExecution } from "../types/workflow-types";

interface UseWorkflowExecutionsResult {
  executions: WorkflowExecution[];
  isLoading: boolean;
  error: Error | null;
  total: number;
  hasMore: boolean;
  loadMore: () => Promise<void>;
  refresh: () => Promise<void>;
}

export function useWorkflowExecutions(
  workflowId: string | undefined,
  limit: number = 10,
): UseWorkflowExecutionsResult {
  const [executions, setExecutions] = useState<WorkflowExecution[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [offset, setOffset] = useState(0);

  const fetchExecutions = useCallback(
    async (reset: boolean = false) => {
      if (!workflowId) return;

      setIsLoading(true);
      setError(null);

      try {
        const currentOffset = reset ? 0 : offset;
        const response = await workflowApi.getWorkflowExecutions(workflowId, {
          limit,
          offset: currentOffset,
        });

        if (reset) {
          setExecutions(response.executions);
          setOffset(limit);
        } else {
          setExecutions((prev) => [...prev, ...response.executions]);
          setOffset((prev) => prev + limit);
        }

        setTotal(response.total);
        setHasMore(response.has_more);
      } catch (err) {
        setError(
          err instanceof Error ? err : new Error("Failed to fetch executions"),
        );
      } finally {
        setIsLoading(false);
      }
    },
    // offset intentionally excluded to avoid re-fetch loop; loadMore passes it explicitly
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [workflowId, limit],
  );

  useEffect(() => {
    if (workflowId) {
      fetchExecutions(true);
    } else {
      setExecutions([]);
      setTotal(0);
      setHasMore(false);
      setOffset(0);
    }
  }, [workflowId, fetchExecutions]);

  const loadMore = useCallback(async () => {
    if (!isLoading && hasMore) {
      await fetchExecutions(false);
    }
  }, [isLoading, hasMore, fetchExecutions]);

  const refresh = useCallback(async () => {
    setOffset(0);
    await fetchExecutions(true);
  }, [fetchExecutions]);

  // Keep a stable ref to the refresh function so the WS handler closure
  // is not recreated on each render.
  const refreshRef = useRef(refresh);
  useEffect(() => {
    refreshRef.current = refresh;
  }, [refresh]);

  useEffect(() => {
    if (!workflowId) return;

    const handleExecutionEvent = (message: unknown) => {
      const msg = message as Record<string, unknown>;
      const eventWorkflowId =
        typeof msg.workflow_id === "string" ? msg.workflow_id : null;

      if (!eventWorkflowId || eventWorkflowId === workflowId) {
        void refreshRef.current();
      }
    };

    const unsubStarted = wsManager.subscribe(
      WS_EVENTS.WORKFLOW_RUN_STARTED,
      handleExecutionEvent,
    );
    const unsubCompleted = wsManager.subscribe(
      WS_EVENTS.WORKFLOW_RUN_COMPLETED,
      handleExecutionEvent,
    );
    const unsubFailed = wsManager.subscribe(
      WS_EVENTS.WORKFLOW_RUN_FAILED,
      handleExecutionEvent,
    );

    return () => {
      unsubStarted();
      unsubCompleted();
      unsubFailed();
    };
  }, [workflowId]);

  return { executions, isLoading, error, total, hasMore, loadMore, refresh };
}

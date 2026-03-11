import { useCallback, useEffect, useState } from "react";
import { workflowApi } from "../api/workflow-api";
import type { WorkflowExecution } from "../types";

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
        const response = await workflowApi.getWorkflowExecutions(
          workflowId,
          limit,
          currentOffset,
        );

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

  return { executions, isLoading, error, total, hasMore, loadMore, refresh };
}

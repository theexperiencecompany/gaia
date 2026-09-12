import { useCallback, useEffect, useRef, useState } from "react";
import { workflowApi } from "../api/workflow-api";
import {
  WORKFLOW_POLLING_INTERVAL_MS,
  WORKFLOW_POLLING_MAX_MS,
} from "../constants/timing";

export type WorkflowExecutionDot = "success" | "failed" | "running" | "idle";

interface UseWorkflowPollingReturn {
  status: WorkflowExecutionDot;
  startPolling: (workflowId: string) => void;
  stopPolling: () => void;
  setStatus: (status: WorkflowExecutionDot) => void;
}

/**
 * Polls workflow run status with a hard 5-minute ceiling so a stuck
 * `running` reply from the backend cannot pin the interval forever.
 */
export function useWorkflowPolling(): UseWorkflowPollingReturn {
  const [status, setStatus] = useState<WorkflowExecutionDot>("idle");
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const stopPolling = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  const startPolling = useCallback(
    (workflowId: string) => {
      stopPolling();

      // Hard ceiling — prevents a runaway poll loop if the backend never
      // reports a terminal state.
      timeoutRef.current = setTimeout(() => {
        stopPolling();
        setStatus("idle");
      }, WORKFLOW_POLLING_MAX_MS);

      intervalRef.current = setInterval(() => {
        workflowApi
          .getWorkflowStatus(workflowId)
          .then((statusResponse) => {
            // The status endpoint reports progress, not a state word: a
            // failure carries an error_message, success is every step done.
            if (statusResponse.error_message) {
              setStatus("failed");
              stopPolling();
            } else if (
              statusResponse.total_steps > 0 &&
              statusResponse.current_step_index >= statusResponse.total_steps
            ) {
              setStatus("success");
              stopPolling();
            }
          })
          .catch(() => {
            // Silent rollback — when the status endpoint isn't shipped yet
            // (404), keep the running state and let the WS event resolve it.
          });
      }, WORKFLOW_POLLING_INTERVAL_MS);
    },
    [stopPolling],
  );

  useEffect(() => stopPolling, [stopPolling]);

  return { status, startPolling, stopPolling, setStatus };
}

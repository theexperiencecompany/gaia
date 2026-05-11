import {
  buildWorkflowStatusEntry,
  isWorkflowStatusFresh,
  WORKFLOW_WS_EVENTS,
} from "@gaia/shared/todos";
import type { Workflow } from "@gaia/shared/types";
import { useEffect, useRef, useState } from "react";
import { wsManager } from "@/lib/websocket-client";
import { todoApi } from "../api/todo-api";
import { useTodoStore } from "../store/todo-store";

interface WorkflowGeneratedEvent {
  todo_id: string;
  workflow: Workflow;
}

interface WorkflowFailedEvent {
  todo_id: string;
  error: string;
}

interface UseTodoWorkflowState {
  workflow: Workflow | null;
  isGenerating: boolean;
  error: string | null;
}

const POLL_DELAYS = [3000, 6000, 12000, 20000];

/**
 * Subscribes to workflow generation events for a single todo and exposes
 * the current workflow state to the detail sheet.
 *
 * Reads from the shared store's `workflowStatusCache` first (avoids a
 * roundtrip when status was prefetched), then falls back to a single API
 * call. While generating, listens to the shared `WORKFLOW_WS_EVENTS` and
 * polls with exponential backoff in case the WebSocket is asleep.
 */
export function useTodoWorkflow(todoId: string | null) {
  const [state, setState] = useState<UseTodoWorkflowState>({
    workflow: null,
    isGenerating: false,
    error: null,
  });
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const setWorkflowStatusEntry = useTodoStore((s) => s.setWorkflowStatusEntry);

  useEffect(() => {
    if (!todoId) {
      setState({ workflow: null, isGenerating: false, error: null });
      return;
    }

    let cancelled = false;

    const cached = useTodoStore.getState().workflowStatusCache[todoId];
    if (isWorkflowStatusFresh(cached)) {
      setState({
        workflow: cached.workflow,
        isGenerating: cached.is_generating,
        error: null,
      });
    } else {
      void todoApi.getWorkflowStatus(todoId).then((status) => {
        if (cancelled) return;
        setWorkflowStatusEntry(todoId, buildWorkflowStatusEntry(status));
        setState({
          workflow: status.workflow,
          isGenerating: status.is_generating,
          error: null,
        });
      });
    }

    const handleGenerated = (msg: unknown) => {
      const event = msg as WorkflowGeneratedEvent;
      if (event.todo_id !== todoId || !event.workflow) return;
      stopPolling();
      setWorkflowStatusEntry(
        todoId,
        buildWorkflowStatusEntry({
          has_workflow: true,
          is_generating: false,
          workflow: event.workflow,
        }),
      );
      setState({
        workflow: event.workflow,
        isGenerating: false,
        error: null,
      });
    };

    const handleFailed = (msg: unknown) => {
      const event = msg as WorkflowFailedEvent;
      if (event.todo_id !== todoId) return;
      stopPolling();
      setState((prev) => ({
        ...prev,
        isGenerating: false,
        error: event.error || "Workflow generation failed",
      }));
    };

    const unsubGenerated = wsManager.subscribe(
      WORKFLOW_WS_EVENTS.WORKFLOW_GENERATED,
      handleGenerated,
    );
    const unsubFailed = wsManager.subscribe(
      WORKFLOW_WS_EVENTS.WORKFLOW_GENERATION_FAILED,
      handleFailed,
    );

    return () => {
      cancelled = true;
      unsubGenerated();
      unsubFailed();
      stopPolling();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [todoId]);

  function stopPolling() {
    if (pollTimerRef.current) {
      clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }

  function startPolling(forTodoId: string) {
    stopPolling();
    let attempt = 0;
    const tick = async () => {
      if (attempt >= POLL_DELAYS.length) return;
      try {
        const status = await todoApi.getWorkflowStatus(forTodoId);
        setWorkflowStatusEntry(forTodoId, buildWorkflowStatusEntry(status));
        if (status.has_workflow && status.workflow) {
          setState({
            workflow: status.workflow,
            isGenerating: false,
            error: null,
          });
          stopPolling();
          return;
        }
        if (
          status.workflow_status === "failed" ||
          status.workflow_status === "not_started"
        ) {
          setState((prev) => ({ ...prev, isGenerating: false }));
          stopPolling();
          return;
        }
      } catch {
        // continue polling on transient failure
      }
      attempt += 1;
      pollTimerRef.current = setTimeout(tick, POLL_DELAYS[attempt - 1]);
    };
    pollTimerRef.current = setTimeout(tick, POLL_DELAYS[0]);
  }

  const generate = async () => {
    if (!todoId || state.isGenerating) return;
    setState((prev) => ({ ...prev, isGenerating: true, error: null }));
    try {
      const result = await todoApi.generateWorkflow(todoId);
      if (result.status === "exists" && result.workflow) {
        setState({
          workflow: result.workflow,
          isGenerating: false,
          error: null,
        });
        return;
      }
      // status === "generating" — start polling fallback
      startPolling(todoId);
    } catch (err) {
      setState({
        workflow: null,
        isGenerating: false,
        error: err instanceof Error ? err.message : "Failed to generate",
      });
    }
  };

  return {
    workflow: state.workflow,
    isGenerating: state.isGenerating,
    error: state.error,
    generate,
  };
}

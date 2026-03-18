import { useCallback, useEffect } from "react";

import { todoApi } from "@/features/todo/api/todoApi";
import { useRouter } from "@/i18n/navigation";
import { toast } from "@/lib/toast";
import { wsManager } from "@/lib/websocket/WebSocketManager";
import { useTodoStore } from "@/stores/todoStore";
import type { Workflow } from "@/types/features/workflowTypes";

interface WorkflowGeneratedMessage {
  type: "workflow.generated";
  todo_id: string;
  workflow: Workflow;
}

interface WorkflowFailedMessage {
  type: "workflow.generation_failed";
  todo_id: string;
  error: string;
}

function extractWorkflowCategories(steps: Workflow["steps"]): string[] {
  return [
    ...new Set(steps.map((s) => s.category).filter((c): c is string => !!c)),
  ].slice(0, 3);
}

/** Apply a completed workflow to the store (shared by WS handler and poller). */
function applyWorkflowToStore(todoId: string, workflow: Workflow) {
  useTodoStore.getState().updateTodoOptimistic(todoId, {
    workflow_id: workflow.id,
    workflow_categories: extractWorkflowCategories(workflow.steps),
  });

  useTodoStore.setState((state) => ({
    workflowStatusCache: {
      ...state.workflowStatusCache,
      [todoId]: {
        has_workflow: true,
        is_generating: false,
        workflow,
        cachedAt: Date.now(),
      },
    },
  }));
}

// Tracks todo IDs that are actively being polled so we can cancel on WS delivery
const pendingPolls = new Set<string>();

/** Poll delays in ms: 3s, 6s, 12s, 20s */
const POLL_DELAYS = [3000, 6000, 12000, 20000];

/**
 * Start polling workflow status for a newly-created todo.
 * Stops early if the WebSocket delivers first (pendingPolls check)
 * or if the workflow is found.
 */
export function startWorkflowPolling(todoId: string) {
  if (pendingPolls.has(todoId)) return;
  pendingPolls.add(todoId);

  const poll = async (attempt: number) => {
    // WebSocket already delivered — stop polling
    if (!pendingPolls.has(todoId)) return;
    if (attempt >= POLL_DELAYS.length) {
      pendingPolls.delete(todoId);
      return;
    }

    try {
      const status = await todoApi.getWorkflowStatus(todoId);

      if (!pendingPolls.has(todoId)) return; // WS arrived during fetch

      if (status.has_workflow && status.workflow) {
        pendingPolls.delete(todoId);
        applyWorkflowToStore(todoId, status.workflow);
        toast.success("Workflow generated!");
        return;
      }

      if (
        status.workflow_status === "failed" ||
        status.workflow_status === "not_started"
      ) {
        pendingPolls.delete(todoId);
        return;
      }
    } catch {
      // Network error — continue polling
    }

    // Schedule next attempt
    setTimeout(() => poll(attempt + 1), POLL_DELAYS[attempt]);
  };

  // Start first poll after initial delay
  setTimeout(() => poll(0), POLL_DELAYS[0]);
}

/**
 * Global WebSocket listener for workflow generation events.
 *
 * Mount once at the app level (ProvidersLayout) so that workflow.generated
 * events update the todo store even when the WorkflowSection sidebar is closed.
 * Also cancels any active polling for the todo.
 */
export function useTodoWorkflowGlobalListener() {
  const router = useRouter();

  const handleGenerated = useCallback(
    (msg: unknown) => {
      const message = msg as WorkflowGeneratedMessage;
      const { todo_id, workflow } = message;

      if (!todo_id || !workflow) return;

      // Cancel polling — WS delivered successfully
      pendingPolls.delete(todo_id);

      applyWorkflowToStore(todo_id, workflow);
      toast.success("Workflow generated!", {
        action: {
          label: "Open",
          onClick: () => router.push(`/todos?todoId=${todo_id}`),
        },
      });
    },
    [router],
  );

  const handleFailed = useCallback((msg: unknown) => {
    const message = msg as WorkflowFailedMessage;
    const { todo_id } = message;

    if (!todo_id) return;

    // Cancel polling
    pendingPolls.delete(todo_id);

    useTodoStore.setState((state) => {
      const { [todo_id]: _, ...rest } = state.workflowStatusCache;
      return { workflowStatusCache: rest };
    });
    toast.error("Failed to generate workflow");
  }, []);

  useEffect(() => {
    wsManager.on("workflow.generated", handleGenerated);
    wsManager.on("workflow.generation_failed", handleFailed);
    return () => {
      wsManager.off("workflow.generated", handleGenerated);
      wsManager.off("workflow.generation_failed", handleFailed);
    };
  }, [handleGenerated, handleFailed]);
}

import { useCallback, useEffect } from "react";

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

type Navigate = (path: string) => void;

let navigate: Navigate | null = null;

const ONBOARDING_ROUTE = /^\/(?:[a-z]{2}(?:-[A-Z]{2})?\/)?onboarding(?:\/|$)/;

function isOnOnboardingRoute(): boolean {
  if (typeof window === "undefined") return false;
  return ONBOARDING_ROUTE.test(window.location.pathname);
}

function notifyWorkflowGenerated(todoId: string) {
  if (isOnOnboardingRoute()) return;
  toast.success(
    "Workflow generated!",
    navigate !== null
      ? {
          action: {
            label: "Open",
            onClick: () => navigate?.(`/todos?todoId=${todoId}`),
          },
        }
      : undefined,
  );
}

function extractWorkflowCategories(steps: Workflow["steps"]): string[] {
  return [
    ...new Set(steps.map((s) => s.category).filter((c): c is string => !!c)),
  ].slice(0, 3);
}

/** Apply a completed workflow to the store. */
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
        workflow: workflow as never,
        cachedAt: Date.now(),
      },
    },
  }));
}

/**
 * Global WebSocket listener for workflow generation events.
 *
 * Mount once at the app level (ProvidersLayout) so that workflow.generated
 * events update the todo store even when the WorkflowSection sidebar is closed.
 */
export function useTodoWorkflowGlobalListener() {
  const router = useRouter();

  useEffect(() => {
    navigate = (path) => router.push(path);
    return () => {
      navigate = null;
    };
  }, [router]);

  const handleGenerated = useCallback((msg: unknown) => {
    const { todo_id, workflow } = msg as WorkflowGeneratedMessage;
    if (!todo_id || !workflow) return;

    applyWorkflowToStore(todo_id, workflow);
    notifyWorkflowGenerated(todo_id);
  }, []);

  const handleFailed = useCallback((msg: unknown) => {
    const { todo_id } = msg as WorkflowFailedMessage;
    if (!todo_id) return;

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

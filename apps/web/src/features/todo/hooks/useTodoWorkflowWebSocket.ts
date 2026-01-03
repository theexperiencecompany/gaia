import { useCallback, useEffect } from "react";

import { wsManager } from "@/lib/websocket";
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

interface UseTodoWorkflowWebSocketOptions {
  todoId: string;
  onWorkflowGenerated?: (workflow: Workflow) => void;
  onWorkflowFailed?: (error: string) => void;
}

/**
 * WebSocket hook for real-time workflow generation events.
 *
 * Listens for:
 * - `workflow.generated`: When workflow generation succeeds
 * - `workflow.generation_failed`: When workflow generation fails
 */
export function useTodoWorkflowWebSocket({
  todoId,
  onWorkflowGenerated,
  onWorkflowFailed,
}: UseTodoWorkflowWebSocketOptions) {
  const handleGenerated = useCallback(
    (msg: unknown) => {
      const message = msg as WorkflowGeneratedMessage;
      if (message.todo_id === todoId && onWorkflowGenerated) {
        onWorkflowGenerated(message.workflow);
      }
    },
    [todoId, onWorkflowGenerated],
  );

  const handleFailed = useCallback(
    (msg: unknown) => {
      const message = msg as WorkflowFailedMessage;
      if (message.todo_id === todoId && onWorkflowFailed) {
        onWorkflowFailed(message.error);
      }
    },
    [todoId, onWorkflowFailed],
  );

  useEffect(() => {
    wsManager.on("workflow.generated", handleGenerated);
    wsManager.on("workflow.generation_failed", handleFailed);
    return () => {
      wsManager.off("workflow.generated", handleGenerated);
      wsManager.off("workflow.generation_failed", handleFailed);
    };
  }, [handleGenerated, handleFailed]);

  return {
    isConnected: wsManager.isConnected,
  };
}

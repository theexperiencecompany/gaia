"use client";

import { useCallback } from "react";
import { workflowApi } from "../api/workflowApi";
import { useWorkflowsStore } from "../stores/workflowsStore";

/**
 * Single source of truth for workflow mutations (API + store). Reusable across
 * the command palette, workflow cards, etc. Confirmation/navigation are the
 * caller's concern.
 */
export function useWorkflowActions() {
  const updateWorkflow = useWorkflowsStore((s) => s.updateWorkflow);
  const removeWorkflow = useWorkflowsStore((s) => s.removeWorkflow);

  const run = useCallback((id: string) => workflowApi.executeWorkflow(id), []);

  const setActivated = useCallback(
    async (id: string, activated: boolean) => {
      if (activated) await workflowApi.deactivateWorkflow(id);
      else await workflowApi.activateWorkflow(id);
      updateWorkflow(id, { activated: !activated });
    },
    [updateWorkflow],
  );

  const remove = useCallback(
    async (id: string) => {
      await workflowApi.deleteWorkflow(id);
      removeWorkflow(id);
    },
    [removeWorkflow],
  );

  return { run, setActivated, remove };
}

export type WorkflowActions = ReturnType<typeof useWorkflowActions>;

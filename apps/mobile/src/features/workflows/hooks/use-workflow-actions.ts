import { useCallback, useState } from "react";
import { workflowApi } from "../api/workflow-api";
import type {
  CreateWorkflowPayload,
  UpdateWorkflowPayload,
  Workflow,
} from "../types/workflow-types";

interface UseWorkflowActionsReturn {
  isCreating: boolean;
  isUpdating: boolean;
  isDeleting: boolean;
  isActivating: boolean;
  isExecuting: boolean;
  createError: string | null;
  actionError: string | null;
  createWorkflow: (payload: CreateWorkflowPayload) => Promise<Workflow | null>;
  updateWorkflow: (
    id: string,
    payload: UpdateWorkflowPayload,
  ) => Promise<Workflow | null>;
  deleteWorkflow: (id: string) => Promise<boolean>;
  toggleActivation: (workflow: Workflow) => Promise<Workflow | null>;
  executeWorkflow: (id: string) => Promise<{ execution_id: string } | null>;
}

export function useWorkflowActions(): UseWorkflowActionsReturn {
  const [isCreating, setIsCreating] = useState(false);
  const [isUpdating, setIsUpdating] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isActivating, setIsActivating] = useState(false);
  const [isExecuting, setIsExecuting] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const createWorkflow = useCallback(
    async (payload: CreateWorkflowPayload): Promise<Workflow | null> => {
      setIsCreating(true);
      setCreateError(null);
      try {
        const response = await workflowApi.createWorkflow(payload);
        return response.workflow;
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to create workflow";
        setCreateError(message);
        return null;
      } finally {
        setIsCreating(false);
      }
    },
    [],
  );

  const updateWorkflow = useCallback(
    async (
      id: string,
      payload: UpdateWorkflowPayload,
    ): Promise<Workflow | null> => {
      setIsUpdating(true);
      setActionError(null);
      try {
        const response = await workflowApi.updateWorkflow(id, payload);
        return response.workflow;
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to update workflow";
        setActionError(message);
        return null;
      } finally {
        setIsUpdating(false);
      }
    },
    [],
  );

  const deleteWorkflow = useCallback(async (id: string): Promise<boolean> => {
    setIsDeleting(true);
    setActionError(null);
    try {
      await workflowApi.deleteWorkflow(id);
      return true;
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to delete workflow";
      setActionError(message);
      return false;
    } finally {
      setIsDeleting(false);
    }
  }, []);

  const toggleActivation = useCallback(
    async (workflow: Workflow): Promise<Workflow | null> => {
      setIsActivating(true);
      setActionError(null);
      try {
        const response = workflow.activated
          ? await workflowApi.deactivateWorkflow(workflow.id)
          : await workflowApi.activateWorkflow(workflow.id);
        return response.workflow;
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to toggle workflow";
        setActionError(message);
        return null;
      } finally {
        setIsActivating(false);
      }
    },
    [],
  );

  const executeWorkflow = useCallback(
    async (id: string): Promise<{ execution_id: string } | null> => {
      setIsExecuting(true);
      setActionError(null);
      try {
        const response = await workflowApi.executeWorkflow(id);
        return { execution_id: response.execution_id };
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to execute workflow";
        setActionError(message);
        return null;
      } finally {
        setIsExecuting(false);
      }
    },
    [],
  );

  return {
    isCreating,
    isUpdating,
    isDeleting,
    isActivating,
    isExecuting,
    createError,
    actionError,
    createWorkflow,
    updateWorkflow,
    deleteWorkflow,
    toggleActivation,
    executeWorkflow,
  };
}

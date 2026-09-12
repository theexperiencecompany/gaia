import { toTriggerConfig } from "@/features/workflows/triggers/types";

("use client");

import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { Dispatch } from "react";
import { useCallback, useMemo, useState } from "react";

import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import type { Integration } from "@/features/integrations/types";
import { useIsPaid } from "@/features/pricing/hooks/useIsPaid";
import { useWorkflowCreation } from "@/features/workflows/hooks/useWorkflowCreation";
import { useRouter } from "@/i18n/navigation";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { toast } from "@/lib/toast";
import { useUpgradeModalStore } from "@/stores/upgradeModalStore";
import type { PublicWorkflowStep } from "@/types/features/workflowTypes";

import { workflowKeys } from "../../api/queryKeys";
import { type Workflow, workflowApi } from "../../api/workflowApi";
import { REGENERATION_REASONS } from "../../constants/regeneration";
import {
  type WorkflowFormData,
  workflowFormSchema,
  workflowToFormData,
} from "../../schemas/workflowFormSchema";
import { findTriggerSchema } from "../../triggers/utils";
import { mentionedIntegrationIds } from "../../utils/integrationMentions";
import { missingIntegrationsMessage } from "../shared/workflowCardHelpers";
import type { WorkflowModalUiAction, WorkflowModalUiState } from "./modalState";

interface UseWorkflowModalActionsParams {
  mode: "create" | "edit" | "preview";
  existingWorkflow?: Workflow | null;
  /** Edit-session working copy — the modal's source of truth after open */
  currentWorkflow: Workflow | null;
  setCurrentWorkflow: (workflow: Workflow | null) => void;
  /** Live form values (react-hook-form watch()) driving change detection */
  formData: WorkflowFormData;
  triggerSchemas: Parameters<typeof findTriggerSchema>[0];
  /** Pre-built steps from a community/public workflow (create flow) */
  hasPredefinedSteps: boolean;
  predefinedSteps?: PublicWorkflowStep[];
  /** Create-and-send immediately executes the workflow in chat after creation */
  createAndSend: boolean;
  onWorkflowSaved?: (workflowId: string) => void;
  onWorkflowDeleted?: (workflowId: string) => void;
  handleClose: () => void;
  /**
   * Modal UI state and its dispatch, owned by WorkflowModal's useReducer.
   * No action reads `ui` today; it is part of the params so an action that
   * needs the current phase does not have to re-plumb it.
   */
  ui: WorkflowModalUiState;
  dispatch: Dispatch<WorkflowModalUiAction>;
}

/**
 * Every mutating action of the workflow modal (create / save / delete /
 * activate / regenerate / publish / run / reset / connect) plus the loading
 * flags they exclusively own. Extracted from WorkflowModal so the component
 * stays focused on form wiring and layout.
 */
export function useWorkflowModalActions({
  mode,
  existingWorkflow,
  currentWorkflow,
  setCurrentWorkflow,
  formData,
  triggerSchemas,
  hasPredefinedSteps,
  predefinedSteps,
  createAndSend,
  onWorkflowSaved,
  onWorkflowDeleted,
  handleClose,
  dispatch,
}: UseWorkflowModalActionsParams) {
  const router = useRouter();

  const {
    isCreating,
    error: creationError,
    createWorkflow,
    clearError: clearCreationError,
  } = useWorkflowCreation();

  const { selectWorkflow } = useWorkflowSelection();

  // Optimistic writes go into the same query key useWorkflows() reads.
  const queryClient = useQueryClient();

  const patchWorkflowInCache = useCallback(
    (workflowId: string, updates: Partial<Workflow>) => {
      queryClient.setQueryData<Workflow[]>(workflowKeys.list(), (workflows) =>
        workflows?.map((workflow) =>
          workflow.id === workflowId ? { ...workflow, ...updates } : workflow,
        ),
      );
    },
    [queryClient],
  );

  const invalidateWorkflows = useCallback(
    () => queryClient.invalidateQueries({ queryKey: workflowKeys.all }),
    [queryClient],
  );

  const snapshotWorkflows = useCallback(async () => {
    await queryClient.cancelQueries({ queryKey: workflowKeys.list() });
    return queryClient.getQueryData<Workflow[]>(workflowKeys.list());
  }, [queryClient]);

  const rollbackWorkflows = useCallback(
    (previous: Workflow[] | undefined) => {
      if (previous) queryClient.setQueryData(workflowKeys.list(), previous);
    },
    [queryClient],
  );

  const activationMutation = useMutation({
    mutationFn: ({
      workflowId,
      activated,
    }: {
      workflowId: string;
      activated: boolean;
    }) =>
      activated
        ? workflowApi.activateWorkflow(workflowId)
        : workflowApi.deactivateWorkflow(workflowId),
    onMutate: async ({ workflowId, activated }) => {
      const previous = await snapshotWorkflows();
      patchWorkflowInCache(workflowId, { activated });
      return { previous };
    },
    onError: (_error, _variables, context) =>
      rollbackWorkflows(context?.previous),
    onSettled: () => invalidateWorkflows(),
  });

  const deleteMutation = useMutation({
    mutationFn: (workflowId: string) => workflowApi.deleteWorkflow(workflowId),
    onMutate: async (workflowId) => {
      const previous = await snapshotWorkflows();
      queryClient.setQueryData<Workflow[]>(workflowKeys.list(), (workflows) =>
        workflows?.filter((workflow) => workflow.id !== workflowId),
      );
      return { previous };
    },
    onError: (_error, _workflowId, context) =>
      rollbackWorkflows(context?.previous),
    onSettled: () => invalidateWorkflows(),
  });

  const { integrations, connectIntegration } = useIntegrations();
  const [connectingId, setConnectingId] = useState<string | null>(null);
  const { isPaid, isUnknown: isSubscriptionStatusUnknown } = useIsPaid();
  const openUpgradeModal = useUpgradeModalStore((s) => s.openModal);

  const [isDeleteConfirmOpen, setIsDeleteConfirmOpen] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  // The integration slugs that step generation hints on (and that get persisted)
  // come from the @-mentions in the instructions. Falls back to the existing
  // workflow's saved slugs for older prompts that predate mention support.
  const selectedIntegrationSlugs = useMemo(() => {
    const mentioned = mentionedIntegrationIds(
      formData.prompt ?? "",
      integrations,
    );
    return mentioned.length > 0
      ? mentioned
      : (existingWorkflow?.integration_ids ?? []);
  }, [formData.prompt, integrations, existingWorkflow]);

  // The integration backing the selected event trigger, if it still needs
  // connecting. Resolved from the selected trigger slug (not trigger_config,
  // which can briefly lag the selection) so this banner always agrees with the
  // settings panel below — same slug, same integration. This one alone gates
  // saving: a trigger that can't fire makes the whole workflow inert.
  const missingTriggerIntegration = useMemo(() => {
    if (formData.activeTab !== "trigger" || !formData.selectedTrigger)
      return null;
    const integrationId = findTriggerSchema(
      triggerSchemas,
      formData.selectedTrigger,
    )?.integration_id;
    if (!integrationId) return null;
    const integration = integrations.find((i) => i.id === integrationId);
    return integration && integration.status !== "connected"
      ? integration
      : null;
  }, [
    formData.activeTab,
    formData.selectedTrigger,
    integrations,
    triggerSchemas,
  ]);

  // Integrations the generated steps require but the user hasn't connected.
  // Sourced from the backend-computed `missing_integrations` (same data the
  // workflow card uses) but re-checked against live connection status so a
  // freshly-connected integration drops out of the banner without a refetch.
  const missingStepIntegrations = useMemo<Integration[]>(() => {
    const refs = currentWorkflow?.missing_integrations ?? [];
    return refs
      .map((ref) => integrations.find((i) => i.id === ref.id))
      .filter((i): i is Integration => !!i && i.status !== "connected");
  }, [currentWorkflow, integrations]);

  // Trigger + step integrations that still need connecting, deduped by id.
  const missingIntegrations = useMemo<Integration[]>(() => {
    const byId = new Map<string, Integration>();
    if (missingTriggerIntegration)
      byId.set(missingTriggerIntegration.id, missingTriggerIntegration);
    for (const integration of missingStepIntegrations)
      byId.set(integration.id, integration);
    return [...byId.values()];
  }, [missingTriggerIntegration, missingStepIntegrations]);

  const handleConnectIntegration = useCallback(
    async (integrationId: string) => {
      if (connectingId) return;
      setConnectingId(integrationId);
      try {
        await connectIntegration(integrationId);
      } catch (err) {
        console.error("Failed to connect integration", err);
      } finally {
        setConnectingId(null);
      }
    },
    [connectingId, connectIntegration],
  );

  // Create a brand-new workflow (optionally with predefined community steps).
  const handleCreate = async (data: WorkflowFormData) => {
    console.debug("[workflow:create] phase -> creating");
    dispatch({ type: "phase", phase: "creating" });

    // Validate the trigger config before sending
    try {
      const validationResult = workflowFormSchema.safeParse(data);
      if (!validationResult.success) {
        dispatch({ type: "phase", phase: "error" });
        return;
      }
    } catch (validationError) {
      console.error("Form validation error:", validationError);
      dispatch({ type: "phase", phase: "error" });
      return;
    }

    // Create the request object that matches the backend API
    const createRequest = {
      title: data.title,
      description: data.description || undefined,
      prompt: data.prompt,
      icon: data.icon ?? undefined,
      icon_color: data.icon_color ?? undefined,
      trigger_config: toTriggerConfig(data.trigger_config),
      // When predefined steps are supplied (from a community/featured
      // workflow), forward them so the backend reuses them instead of
      // regenerating a fresh plan.
      steps: hasPredefinedSteps
        ? predefinedSteps?.map((step) => ({
            id: step.id ?? "",
            title: step.title,
            description: step.description,
            category: step.category,
          }))
        : undefined,
      generate_immediately: !hasPredefinedSteps,
      notify_on_completion: data.notify_on_completion,
      integration_ids:
        selectedIntegrationSlugs.length > 0
          ? selectedIntegrationSlugs
          : undefined,
    };

    const result = await createWorkflow(createRequest);
    console.debug("[workflow:create] api returned", {
      success: result.success,
      id: result.workflow?.id,
      steps: result.workflow?.steps?.length ?? 0,
    });

    if (!result.success || !result.workflow) {
      dispatch({ type: "phase", phase: "error" });
      return;
    }

    const createdWorkflow = result.workflow;
    trackEvent(ANALYTICS_EVENTS.WORKFLOWS_CREATED, {
      workflow_id: createdWorkflow.id,
      // workflow_title is user-authored free text — never sent to PostHog.
      step_count: createdWorkflow.steps?.length || 0,
      trigger_type: data.trigger_config.type,
      has_schedule: data.trigger_config.type === "schedule",
    });

    // Update currentWorkflow with the newly created workflow
    setCurrentWorkflow(createdWorkflow);
    console.debug("[workflow:create] phase -> success");
    dispatch({ type: "phase", phase: "success" });

    // Show success toast
    toast.success("Workflow created successfully!", {
      description: `${createdWorkflow.steps?.length || 0} steps generated`,
      duration: 3000,
    });

    // Optimistic update: show it in the list immediately
    queryClient.setQueryData<Workflow[]>(
      workflowKeys.list(),
      (workflows = []) => [createdWorkflow, ...workflows],
    );

    // Notify parent callbacks if provided (for backwards compatibility)
    if (onWorkflowSaved) onWorkflowSaved(createdWorkflow.id);
    await invalidateWorkflows();

    // In createAndSend mode, selectWorkflow navigates to /c and unmounts
    // this page (and modal). Closing here would push back to /workflows
    // and clobber that navigation, so only close when staying on the page.
    if (createAndSend) {
      selectWorkflow(createdWorkflow, { autoSend: true });
    } else {
      handleClose();
    }
  };

  // Regenerate steps after an edit that changed step-relevant fields. Keeps the
  // modal open with a visible indicator until the user dismisses it.
  const regenerateStepsAfterEdit = async (workflow: Workflow) => {
    console.debug(
      "[workflow:regen] step-relevant change detected, regenerating",
      {
        id: workflow.id,
      },
    );
    dispatch({ type: "regenerating", value: true });
    dispatch({ type: "regenerationError", message: null });
    try {
      const regenResult = await workflowApi.regenerateWorkflowSteps(
        workflow.id,
        {
          instruction: "Update steps to match the new workflow definition",
          force_different_tools: false,
          integration_ids:
            selectedIntegrationSlugs.length > 0
              ? selectedIntegrationSlugs
              : undefined,
        },
      );

      if (regenResult.workflow) {
        console.debug("[workflow:regen] api returned new steps", {
          id: workflow.id,
          steps: regenResult.workflow.steps?.length ?? 0,
        });
        // Commit the new steps locally AND to the cache so the upcoming
        // refetch can't briefly resurface the old steps.
        setCurrentWorkflow(regenResult.workflow);
        patchWorkflowInCache(workflow.id, regenResult.workflow);
        toast.success("Workflow updated", {
          description: `${regenResult.workflow.steps?.length || 0} steps regenerated`,
          duration: 3000,
        });
      }
    } catch (regenError) {
      console.error("Failed to regenerate steps after update:", regenError);
      const message =
        regenError instanceof Error
          ? regenError.message
          : "Failed to regenerate steps";
      dispatch({ type: "regenerationError", message });
      toast.error("Saved, but failed to regenerate steps", {
        description: message,
      });
    } finally {
      dispatch({ type: "regenerating", value: false });
    }
  };

  // Persist edits to an existing workflow, regenerating steps if needed.
  const handleUpdate = async (data: WorkflowFormData) => {
    if (!currentWorkflow) return;

    try {
      const updateRequest = {
        title: data.title,
        description: data.description || undefined,
        prompt: data.prompt,
        icon: data.icon,
        icon_color: data.icon_color,
        trigger_config: toTriggerConfig(data.trigger_config),
        notify_on_completion: data.notify_on_completion,
        integration_ids: selectedIntegrationSlugs,
      };

      // Decide if step regeneration is needed BEFORE persisting,
      // so the comparison runs against the previous truth.
      const previousFormData = workflowToFormData(currentWorkflow);
      const previousSlugs = [...(currentWorkflow.integration_ids ?? [])]
        .sort((a, b) => a.localeCompare(b))
        .join(",");
      const currentSlugs = [...selectedIntegrationSlugs]
        .sort((a, b) => a.localeCompare(b))
        .join(",");
      const stepRelevantChanged =
        data.prompt !== previousFormData.prompt ||
        data.description !== previousFormData.description ||
        JSON.stringify(data.trigger_config) !==
          JSON.stringify(previousFormData.trigger_config) ||
        previousSlugs !== currentSlugs;

      const updatedWorkflow = await workflowApi.updateWorkflow(
        currentWorkflow.id,
        updateRequest,
      );

      if (updatedWorkflow?.workflow) {
        setCurrentWorkflow(updatedWorkflow.workflow);
        patchWorkflowInCache(currentWorkflow.id, updatedWorkflow.workflow);
      } else {
        patchWorkflowInCache(currentWorkflow.id, updateRequest);
      }

      if (stepRelevantChanged) {
        await regenerateStepsAfterEdit(currentWorkflow);
      } else {
        toast.success("Workflow updated", { duration: 3000 });
      }

      if (onWorkflowSaved) onWorkflowSaved(currentWorkflow.id);

      await invalidateWorkflows();
    } catch (error) {
      console.error("Failed to update workflow:", error);
      toast.error("Failed to update workflow", {
        description:
          error instanceof Error
            ? error.message
            : "An unexpected error occurred. Please try again.",
        duration: 4000,
      });
    }
  };

  const handleSave = async (data: WorkflowFormData) => {
    if (!data.title.trim() || !data.prompt?.trim()) return;

    console.debug("[workflow:save] start", {
      mode,
      title: data.title,
      integrations: selectedIntegrationSlugs,
    });

    if (mode === "create") {
      await handleCreate(data);
      return;
    }

    // Edit mode - update the existing workflow
    await handleUpdate(data);
  };

  const handleDelete = () => {
    if (mode === "edit" && existingWorkflow) {
      setIsDeleteConfirmOpen(true);
    }
  };

  const confirmDelete = async () => {
    if (!(mode === "edit" && existingWorkflow)) return;
    setIsDeleting(true);
    try {
      trackEvent(ANALYTICS_EVENTS.WORKFLOWS_DELETED, {
        workflow_id: existingWorkflow.id,
        step_count: existingWorkflow.steps?.length || 0,
        is_public: existingWorkflow.is_public,
      });

      await deleteMutation.mutateAsync(existingWorkflow.id);

      if (onWorkflowDeleted) onWorkflowDeleted(existingWorkflow.id);

      setIsDeleteConfirmOpen(false);
      handleClose();
    } catch (error) {
      console.error("Failed to delete workflow:", error);
      toast.error("Failed to delete workflow", {
        description:
          error instanceof Error
            ? error.message
            : "An unexpected error occurred",
        duration: 4000,
      });
    } finally {
      setIsDeleting(false);
    }
  };

  // Handle activation toggle
  const handleActivationToggle = async (newActivated: boolean) => {
    if (mode !== "edit" || !currentWorkflow) return;

    // GAIA is paid-only: a free user can't enable a workflow. Show the
    // upsell toast and open the paywall — never call activateWorkflow. While
    // the subscription-status is still unknown, let the toggle proceed (the
    // backend is the backstop) rather than gating on a not-yet-resolved
    // "false".
    if (newActivated && !isSubscriptionStatusUnknown && !isPaid) {
      toast.info("Workflows require GAIA Pro", {
        action: {
          label: "Upgrade",
          onClick: () =>
            openUpgradeModal(undefined, { source: "workflow_activation" }),
        },
      });
      return;
    }

    // Block enabling a workflow whose trigger/steps need unconnected
    // integrations — it could never actually run.
    if (newActivated && missingIntegrations.length > 0) {
      toast.error("Can't enable this workflow", {
        description: missingIntegrationsMessage(missingIntegrations),
      });
      return;
    }

    dispatch({ type: "togglingActivation", value: true });
    try {
      await activationMutation.mutateAsync({
        workflowId: currentWorkflow.id,
        activated: newActivated,
      });

      // Update currentWorkflow activation state
      setCurrentWorkflow({
        ...currentWorkflow,
        activated: newActivated,
      });
      dispatch({ type: "activated", value: newActivated });
    } catch (error) {
      console.error("Failed to toggle workflow activation:", error);
    } finally {
      dispatch({ type: "togglingActivation", value: false });
    }
  };

  // Handle step regeneration
  const handleRegenerateSteps = async (
    instruction: string = "Generate alternative workflow approach",
    forceDifferentTools: boolean = true,
  ) => {
    if (mode !== "edit" || !currentWorkflow) return;

    trackEvent(ANALYTICS_EVENTS.WORKFLOWS_STEPS_REGENERATED, {
      workflow_id: currentWorkflow.id,
      // The instruction is user-authored free text (often contains the goal
      // or context of the workflow) — never send it to PostHog, only its length.
      instruction_length: instruction.length,
      force_different_tools: forceDifferentTools,
      previous_step_count: currentWorkflow.steps?.length || 0,
    });

    dispatch({ type: "regenerating", value: true });
    dispatch({ type: "regenerationError", message: null });

    try {
      const result = await workflowApi.regenerateWorkflowSteps(
        currentWorkflow.id,
        {
          instruction,
          force_different_tools: forceDifferentTools,
          integration_ids:
            selectedIntegrationSlugs.length > 0
              ? selectedIntegrationSlugs
              : undefined,
        },
      );

      // Update workflow with new steps immediately
      if (result.workflow) {
        setCurrentWorkflow(result.workflow);

        toast.success("Steps regenerated successfully!", {
          description: `${result.workflow.steps?.length || 0} new steps created`,
          duration: 3000,
        });
      }

      if (onWorkflowSaved) onWorkflowSaved(currentWorkflow.id);
      await invalidateWorkflows();

      dispatch({ type: "regenerating", value: false });
    } catch (error) {
      console.error("Failed to regenerate workflow steps:", error);
      const errorMessage =
        error instanceof Error
          ? error.message
          : "Failed to regenerate workflow steps";
      dispatch({ type: "regenerationError", message: errorMessage });
      dispatch({ type: "regenerating", value: false });
    }
  };

  const handlePublishToggle = async () => {
    if (!currentWorkflow?.id) return;
    try {
      if (currentWorkflow.is_public) {
        trackEvent(ANALYTICS_EVENTS.WORKFLOWS_UNPUBLISHED, {
          workflow_id: currentWorkflow.id,
        });
        await workflowApi.unpublishWorkflow(currentWorkflow.id);
        setCurrentWorkflow({ ...currentWorkflow, is_public: false });
      } else {
        trackEvent(ANALYTICS_EVENTS.WORKFLOWS_PUBLISHED, {
          workflow_id: currentWorkflow.id,
          step_count: currentWorkflow.steps?.length || 0,
        });
        const result = await workflowApi.publishWorkflow(currentWorkflow.id);
        const slug = result.slug ?? currentWorkflow.slug;
        setCurrentWorkflow({ ...currentWorkflow, is_public: true, slug });
        if (slug) router.push(`/use-cases/${slug}`);
      }
      await invalidateWorkflows();
    } catch (error) {
      console.error("Error publishing/unpublishing workflow:", error);
    }
  };

  const handleMarketplaceView = () => {
    if (!currentWorkflow?.slug) return;
    router.push(`/use-cases/${currentWorkflow.slug}`);
  };

  // Handle workflow execution
  const handleRunWorkflow = async () => {
    if (mode !== "edit" || !existingWorkflow) return;

    // Check if workflow has steps before allowing execution
    if (!currentWorkflow?.steps || currentWorkflow.steps.length === 0) {
      toast.error("Cannot run workflow", {
        description:
          "This workflow doesn't have any steps generated yet. Please wait for step generation to complete.",
        duration: 4000,
      });
      return;
    }

    try {
      trackEvent(ANALYTICS_EVENTS.WORKFLOWS_EXECUTED, {
        workflow_id: existingWorkflow.id,
        step_count: currentWorkflow.steps.length,
        trigger_type: existingWorkflow.trigger_config.type,
      });

      // selectWorkflow navigates to /c, which unmounts this page (and modal).
      // Do NOT close the modal here: the parent's close handler pushes back to
      // /workflows, which would clobber the /c navigation in the same tick.
      selectWorkflow(existingWorkflow, { autoSend: true });
    } catch (error) {
      console.error("Failed to select workflow for execution:", error);
    }
  };

  const handleResetToDefault = async () => {
    if (!existingWorkflow?.id) return;
    try {
      await workflowApi.resetToDefault(existingWorkflow.id);
      await invalidateWorkflows();
      handleClose();
    } catch (error) {
      toast.error("Failed to reset workflow", {
        description:
          error instanceof Error
            ? error.message
            : "An unexpected error occurred",
        duration: 4000,
      });
    }
  };

  // Handle regeneration with a specific reason. The reason's instruction is the
  // single source of truth in constants/regeneration.ts (shared with the panel).
  const handleRegenerateWithReason = (instructionKey: string) => {
    const reason = REGENERATION_REASONS.find((r) => r.key === instructionKey);
    if (reason) {
      handleRegenerateSteps(reason.instruction, true); // Always force different tools
    }
  };

  // Handle initial step generation (for empty workflows)
  const handleInitialGeneration = () => {
    handleRegenerateSteps("Generate workflow steps", false); // Don't force different tools for initial generation
  };

  return {
    isCreating,
    creationError,
    clearCreationError,
    connectingId,
    isDeleting,
    isDeleteConfirmOpen,
    setIsDeleteConfirmOpen,
    selectedIntegrationSlugs,
    missingTriggerIntegration,
    missingIntegrations,
    handleConnectIntegration,
    handleSave,
    handleDelete,
    confirmDelete,
    handleActivationToggle,
    handleRegenerateSteps,
    handleRegenerateWithReason,
    handleInitialGeneration,
    handlePublishToggle,
    handleMarketplaceView,
    handleRunWorkflow,
    handleResetToDefault,
  };
}

"use client";

import { Button } from "@heroui/button";
import { Divider } from "@heroui/divider";
import { Modal, ModalBody, ModalContent } from "@heroui/modal";
import { Switch } from "@heroui/switch";
import { zodResolver } from "@hookform/resolvers/zod";
import { InformationCircleIcon } from "@icons";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  type Control,
  type FieldErrors,
  type UseFormSetValue,
  useForm,
} from "react-hook-form";
import { useHotkeys } from "react-hotkeys-hook";
import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import type { Integration } from "@/features/integrations/types";
import {
  MissingIntegrationsAlert,
  missingIntegrationsMessage,
} from "@/features/workflows/components/shared/WorkflowCardComponents";
import WorkflowDescriptionField from "@/features/workflows/components/workflow-modal/WorkflowDescriptionField";
import WorkflowFooter from "@/features/workflows/components/workflow-modal/WorkflowFooter";
import WorkflowHeader from "@/features/workflows/components/workflow-modal/WorkflowHeader";
import WorkflowLoadingState from "@/features/workflows/components/workflow-modal/WorkflowLoadingState";
import WorkflowRightPanel from "@/features/workflows/components/workflow-modal/WorkflowRightPanel";
import WorkflowStepsPreviewCard from "@/features/workflows/components/workflow-modal/WorkflowStepsPreviewCard";
import WorkflowTriggerSection from "@/features/workflows/components/workflow-modal/WorkflowTriggerSection";
import { useWorkflowCreation } from "@/features/workflows/hooks/useWorkflowCreation";
import { usePlatform } from "@/hooks/ui/usePlatform";
import { useRouter } from "@/i18n/navigation";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { getUserHomeTimezone } from "@/lib/timezone";
import { toast } from "@/lib/toast";
import type { WorkflowDraftData } from "@/types/features/toolDataTypes";
import type { PublicWorkflowStep } from "@/types/features/workflowTypes";
import { type Workflow, workflowApi } from "../api/workflowApi";
import { REGENERATION_REASONS } from "../constants/regeneration";
import {
  getDefaultFormValues,
  type WorkflowFormData,
  workflowFormSchema,
  workflowToFormData,
} from "../schemas/workflowFormSchema";
import { useWorkflowModalStore } from "../stores/workflowModalStore";
import { useWorkflowsStore } from "../stores/workflowsStore";
import { useTriggerSchemas } from "../triggers/hooks/useTriggerSchemas";
import { createDefaultTriggerConfig } from "../triggers/registry";
import { hasValidTriggerName, isIntegrationTrigger } from "../triggers/types";
import { findTriggerSchema } from "../triggers/utils";
import { mentionedIntegrationIds } from "../utils/integrationMentions";

interface WorkflowModalProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onWorkflowSaved?: (workflowId: string) => void;
  onWorkflowDeleted?: (workflowId: string) => void;
  mode: "create" | "edit" | "preview";
  existingWorkflow?: Workflow | null;
  draftData?: WorkflowDraftData | null;
  predefinedSteps?: PublicWorkflowStep[];
  createAndSend?: boolean;
}

function buildDraftFormValues(
  draftData: WorkflowDraftData,
  triggerSchemas: Parameters<typeof findTriggerSchema>[0],
): WorkflowFormData {
  const activeTab =
    draftData.trigger_type === "schedule"
      ? "schedule"
      : draftData.trigger_type === "integration"
        ? "trigger"
        : "manual";
  let triggerConfig: WorkflowFormData["trigger_config"];
  let selectedTriggerValue = "";
  if (draftData.trigger_type === "schedule") {
    triggerConfig = {
      type: "schedule" as const,
      enabled: true,
      cron_expression: draftData.cron_expression || "0 9 * * *",
      timezone: getUserHomeTimezone(),
    };
  } else if (
    draftData.trigger_type === "integration" &&
    draftData.trigger_slug
  ) {
    const schema = findTriggerSchema(triggerSchemas, draftData.trigger_slug);
    const normalizedSlug = schema?.slug ?? draftData.trigger_slug;
    const defaultConfig = createDefaultTriggerConfig(normalizedSlug);
    if (defaultConfig) {
      triggerConfig = {
        ...defaultConfig,
        trigger_slug: normalizedSlug,
      };
    } else {
      triggerConfig = {
        type: normalizedSlug,
        enabled: true,
        trigger_name: normalizedSlug,
      };
    }
    selectedTriggerValue = normalizedSlug;
  } else {
    triggerConfig = {
      type: "manual" as const,
      enabled: true,
    };
  }
  return {
    title: draftData.suggested_title,
    description: draftData.suggested_description || undefined,
    prompt: draftData.prompt || draftData.suggested_description || "",
    icon: null,
    icon_color: null,
    activeTab,
    selectedTrigger: selectedTriggerValue,
    trigger_config: triggerConfig,
    notify_on_completion: true,
  };
}

function useWorkflowDerivedIntegrations({
  formData,
  integrations,
  triggerSchemas,
  currentWorkflow,
  existingWorkflow,
}: {
  formData: WorkflowFormData;
  integrations: Integration[];
  triggerSchemas: ReturnType<typeof useTriggerSchemas>["data"];
  currentWorkflow: Workflow | null;
  existingWorkflow?: Workflow | null;
}) {
  const selectedIntegrationSlugs = useMemo(() => {
    const mentioned = mentionedIntegrationIds(
      formData.prompt ?? "",
      integrations,
    );
    return mentioned.length > 0
      ? mentioned
      : (existingWorkflow?.integration_ids ?? []);
  }, [formData.prompt, integrations, existingWorkflow]);
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
  const missingStepIntegrations = useMemo<Integration[]>(() => {
    const refs = currentWorkflow?.missing_integrations ?? [];
    return refs
      .map((ref) => integrations.find((i) => i.id === ref.id))
      .filter((i): i is Integration => !!i && i.status !== "connected");
  }, [currentWorkflow, integrations]);
  const missingIntegrations = useMemo<Integration[]>(() => {
    const byId = new Map<string, Integration>();
    if (missingTriggerIntegration)
      byId.set(missingTriggerIntegration.id, missingTriggerIntegration);
    for (const integration of missingStepIntegrations)
      byId.set(integration.id, integration);
    return [...byId.values()];
  }, [missingTriggerIntegration, missingStepIntegrations]);
  return {
    selectedIntegrationSlugs,
    missingTriggerIntegration,
    missingStepIntegrations,
    missingIntegrations,
  };
}

function useWorkflowFormGuards({
  formData,
  mode,
  existingWorkflow,
  selectedIntegrationSlugs,
  isCreating,
  missingTriggerIntegration,
}: {
  formData: WorkflowFormData;
  mode: "create" | "edit" | "preview";
  existingWorkflow?: Workflow | null;
  selectedIntegrationSlugs: string[];
  isCreating: boolean;
  missingTriggerIntegration: Integration | null;
}) {
  const hasFormChanges = useCallback(() => {
    if (mode === "create") return true;
    if (!existingWorkflow) return true;
    const currentFormData = workflowToFormData(existingWorkflow);
    const persistedSlugs = [...(existingWorkflow.integration_ids ?? [])]
      .sort((a, b) => a.localeCompare(b))
      .join(",");
    const currentSlugs = [...selectedIntegrationSlugs]
      .sort((a, b) => a.localeCompare(b))
      .join(",");
    return (
      formData.title !== currentFormData.title ||
      formData.description !== currentFormData.description ||
      formData.prompt !== currentFormData.prompt ||
      formData.icon !== currentFormData.icon ||
      formData.icon_color !== currentFormData.icon_color ||
      formData.activeTab !== currentFormData.activeTab ||
      formData.selectedTrigger !== currentFormData.selectedTrigger ||
      JSON.stringify(formData.trigger_config) !==
        JSON.stringify(currentFormData.trigger_config) ||
      persistedSlugs !== currentSlugs
    );
  }, [mode, existingWorkflow, formData, selectedIntegrationSlugs]);
  const isSaveDisabled = useCallback(() => {
    if (!formData.title.trim() || !formData.prompt?.trim()) return true;
    if (
      formData.activeTab === "schedule" &&
      formData.trigger_config.type === "schedule" &&
      !formData.trigger_config.cron_expression
    )
      return true;
    if (formData.activeTab === "trigger" && !formData.selectedTrigger)
      return true;
    if (
      isIntegrationTrigger(formData.trigger_config) &&
      !hasValidTriggerName(formData.trigger_config)
    )
      return true;
    if (missingTriggerIntegration) return true;
    if (mode === "edit" && !hasFormChanges()) return true;
    if (isCreating) return true;
    return false;
  }, [formData, mode, isCreating, missingTriggerIntegration, hasFormChanges]);
  return { hasFormChanges, isSaveDisabled };
}

function useWorkflowModalSync({
  isOpen,
  mode,
  currentWorkflow,
  existingWorkflow,
  draftData,
  triggerSchemas,
  resetFormValues,
  setIsActivated,
  setCreationPhase,
  setCurrentWorkflow,
  clearCreationError,
  resetToForm,
}: {
  isOpen: boolean;
  mode: "create" | "edit" | "preview";
  currentWorkflow: Workflow | null;
  existingWorkflow?: Workflow | null;
  draftData?: WorkflowDraftData | null;
  triggerSchemas: ReturnType<typeof useTriggerSchemas>["data"];
  resetFormValues: (values: WorkflowFormData) => void;
  setIsActivated: (val: boolean) => void;
  setCreationPhase: (phase: "form" | "creating" | "success" | "error") => void;
  setCurrentWorkflow: (w: Workflow | null) => void;
  clearCreationError: () => void;
  resetToForm: () => void;
}) {
  useEffect(() => {
    if (isOpen) return;
    const timer = globalThis.setTimeout(() => {
      resetFormValues(getDefaultFormValues());
    }, 250);
    return () => globalThis.clearTimeout(timer);
  }, [isOpen, resetFormValues]);
  const wasOpenRef = useRef(false);
  useEffect(() => {
    if (isOpen && !wasOpenRef.current) {
      resetToForm();
      clearCreationError();
    }
    wasOpenRef.current = isOpen;
  }, [isOpen, resetToForm, clearCreationError, mode]);
  const syncedWorkflowIdRef = useRef<string | null>(null);
  useEffect(() => {
    const nextId = existingWorkflow?.id ?? null;
    if (nextId === syncedWorkflowIdRef.current) return;
    syncedWorkflowIdRef.current = nextId;
    setCurrentWorkflow(existingWorkflow ?? null);
  }, [existingWorkflow, setCurrentWorkflow]);
  useEffect(() => {
    if ((mode === "edit" || mode === "preview") && currentWorkflow) {
      const formValues = workflowToFormData(currentWorkflow);
      resetFormValues(formValues);
      setIsActivated(currentWorkflow.activated);
      setCreationPhase("form");
      return;
    }
    if (mode === "create" && draftData) {
      resetFormValues(buildDraftFormValues(draftData, triggerSchemas));
      setIsActivated(true);
      setCreationPhase("form");
      return;
    }
    resetFormValues(getDefaultFormValues());
    setIsActivated(true);
    setCreationPhase("form");
  }, [
    mode,
    currentWorkflow,
    draftData,
    triggerSchemas,
    resetFormValues,
    setIsActivated,
    setCreationPhase,
  ]);
}

function useWorkflowModalActions({
  mode,
  currentWorkflow,
  setCurrentWorkflow,
  existingWorkflow,
  hasPredefinedSteps,
  predefinedSteps,
  selectedIntegrationSlugs,
  createWorkflow,
  setCreationPhase,
  addToStore,
  updateInStore,
  removeFromStore,
  fetchWorkflows,
  invalidateCache,
  onWorkflowSaved,
  onWorkflowDeleted,
  selectWorkflow,
  createAndSend,
  handleClose,
  setIsDeleteConfirmOpen,
  setIsDeleting,
  setIsRegeneratingSteps,
  setRegenerationError,
  setIsTogglingActivation,
  setIsActivated,
  isCreating,
  router,
}: {
  mode: "create" | "edit" | "preview";
  currentWorkflow: Workflow | null;
  setCurrentWorkflow: (w: Workflow | null) => void;
  existingWorkflow?: Workflow | null;
  hasPredefinedSteps: boolean;
  predefinedSteps?: PublicWorkflowStep[];
  selectedIntegrationSlugs: string[];
  createWorkflow: ReturnType<typeof useWorkflowCreation>["createWorkflow"];
  setCreationPhase: (phase: "form" | "creating" | "success" | "error") => void;
  addToStore: (w: Workflow) => void;
  updateInStore: (id: string, data: Partial<Workflow>) => void;
  removeFromStore: (id: string) => void;
  fetchWorkflows: () => Promise<void>;
  invalidateCache: () => void;
  onWorkflowSaved?: (id: string) => void;
  onWorkflowDeleted?: (id: string) => void;
  selectWorkflow: ReturnType<typeof useWorkflowSelection>["selectWorkflow"];
  createAndSend: boolean;
  handleClose: () => void;
  setIsDeleteConfirmOpen: (open: boolean) => void;
  setIsDeleting: (deleting: boolean) => void;
  setIsRegeneratingSteps: (val: boolean) => void;
  setRegenerationError: (msg: string | null) => void;
  setIsTogglingActivation: (val: boolean) => void;
  setIsActivated: (val: boolean) => void;
  isCreating: boolean;
  router: ReturnType<typeof useRouter>;
}) {
  const regenerateStepsAfterEdit = useCallback(
    async (workflow: Workflow) => {
      setIsRegeneratingSteps(true);
      setRegenerationError(null);
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
          setCurrentWorkflow(regenResult.workflow);
          updateInStore(workflow.id, regenResult.workflow);
          toast.success("Workflow updated", {
            description: `${regenResult.workflow.steps?.length || 0} steps regenerated`,
            duration: 3000,
          });
        }
      } catch (regenError) {
        const message =
          regenError instanceof Error
            ? regenError.message
            : "Failed to regenerate steps";
        setRegenerationError(message);
        toast.error("Saved, but failed to regenerate steps", {
          description: message,
        });
      } finally {
        setIsRegeneratingSteps(false);
      }
    },
    [
      selectedIntegrationSlugs,
      setCurrentWorkflow,
      setIsRegeneratingSteps,
      setRegenerationError,
      updateInStore,
    ],
  );
  const handleCreate = useCallback(
    async (data: WorkflowFormData) => {
      setCreationPhase("creating");
      try {
        const validationResult = workflowFormSchema.safeParse(data);
        if (!validationResult.success) {
          setCreationPhase("error");
          return;
        }
      } catch (validationError) {
        console.error("Form validation error:", validationError);
        setCreationPhase("error");
        return;
      }
      const createRequest = {
        title: data.title,
        description: data.description || undefined,
        prompt: data.prompt,
        icon: data.icon ?? undefined,
        icon_color: data.icon_color ?? undefined,
        trigger_config: data.trigger_config,
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
      if (!result.success || !result.workflow) {
        setCreationPhase("error");
        return;
      }
      const createdWorkflow = result.workflow;
      trackEvent(ANALYTICS_EVENTS.WORKFLOWS_CREATED, {
        workflow_id: createdWorkflow.id,
        step_count: createdWorkflow.steps?.length || 0,
        trigger_type: data.trigger_config.type,
        has_schedule: data.trigger_config.type === "schedule",
      });
      setCurrentWorkflow(createdWorkflow);
      setCreationPhase("success");
      toast.success("Workflow created successfully!", {
        description: `${createdWorkflow.steps?.length || 0} steps generated`,
        duration: 3000,
      });
      addToStore(createdWorkflow);
      if (onWorkflowSaved) onWorkflowSaved(createdWorkflow.id);
      invalidateCache();
      await fetchWorkflows();
      if (createAndSend) {
        selectWorkflow(createdWorkflow, { autoSend: true });
      } else {
        handleClose();
      }
    },
    [
      addToStore,
      createAndSend,
      createWorkflow,
      fetchWorkflows,
      handleClose,
      hasPredefinedSteps,
      invalidateCache,
      onWorkflowSaved,
      predefinedSteps,
      selectWorkflow,
      selectedIntegrationSlugs,
      setCreationPhase,
      setCurrentWorkflow,
    ],
  );
  const handleUpdate = useCallback(
    async (data: WorkflowFormData) => {
      if (!currentWorkflow) return;
      try {
        const updateRequest = {
          title: data.title,
          description: data.description || undefined,
          prompt: data.prompt,
          icon: data.icon,
          icon_color: data.icon_color,
          trigger_config: { ...data.trigger_config },
          notify_on_completion: data.notify_on_completion,
          integration_ids: selectedIntegrationSlugs,
        };
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
          updateInStore(currentWorkflow.id, updatedWorkflow.workflow);
        } else {
          updateInStore(currentWorkflow.id, updateRequest);
        }
        if (stepRelevantChanged) {
          await regenerateStepsAfterEdit(currentWorkflow);
        } else {
          toast.success("Workflow updated", { duration: 3000 });
        }
        if (onWorkflowSaved) onWorkflowSaved(currentWorkflow.id);
        invalidateCache();
        await fetchWorkflows();
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
    },
    [
      currentWorkflow,
      fetchWorkflows,
      invalidateCache,
      onWorkflowSaved,
      regenerateStepsAfterEdit,
      selectedIntegrationSlugs,
      setCurrentWorkflow,
      updateInStore,
    ],
  );
  const handleSave = useCallback(
    async (data: WorkflowFormData) => {
      if (!data.title.trim() || !data.prompt?.trim()) return;
      if (mode === "create") {
        await handleCreate(data);
        return;
      }
      await handleUpdate(data);
    },
    [handleCreate, handleUpdate, mode],
  );
  const handleResetToDefault = useCallback(async () => {
    if (!existingWorkflow?.id) return;
    try {
      await workflowApi.resetToDefault(existingWorkflow.id);
      invalidateCache();
      await fetchWorkflows();
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
  }, [existingWorkflow?.id, fetchWorkflows, handleClose, invalidateCache]);
  const handleDelete = useCallback(() => {
    if (mode === "edit" && existingWorkflow) {
      setIsDeleteConfirmOpen(true);
    }
  }, [mode, existingWorkflow, setIsDeleteConfirmOpen]);
  const confirmDelete = useCallback(async () => {
    if (!(mode === "edit" && existingWorkflow)) return;
    setIsDeleting(true);
    try {
      trackEvent(ANALYTICS_EVENTS.WORKFLOWS_DELETED, {
        workflow_id: existingWorkflow.id,
        step_count: existingWorkflow.steps?.length || 0,
        is_public: existingWorkflow.is_public,
      });
      await workflowApi.deleteWorkflow(existingWorkflow.id);
      removeFromStore(existingWorkflow.id);
      if (onWorkflowDeleted) onWorkflowDeleted(existingWorkflow.id);
      invalidateCache();
      await fetchWorkflows();
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
  }, [
    existingWorkflow,
    fetchWorkflows,
    handleClose,
    invalidateCache,
    mode,
    onWorkflowDeleted,
    removeFromStore,
    setIsDeleting,
    setIsDeleteConfirmOpen,
  ]);
  const handleActivationToggle = useCallback(
    async (newActivated: boolean, missingIntegrations: Integration[]) => {
      if (mode !== "edit" || !currentWorkflow) return;
      if (newActivated && missingIntegrations.length > 0) {
        toast.error("Can't enable this workflow", {
          description: missingIntegrationsMessage(missingIntegrations),
        });
        return;
      }
      setIsTogglingActivation(true);
      try {
        if (newActivated) {
          await workflowApi.activateWorkflow(currentWorkflow.id);
        } else {
          await workflowApi.deactivateWorkflow(currentWorkflow.id);
        }
        setCurrentWorkflow({ ...currentWorkflow, activated: newActivated });
        setIsActivated(newActivated);
        updateInStore(currentWorkflow.id, { activated: newActivated });
        invalidateCache();
        await fetchWorkflows();
      } catch (error) {
        console.error("Failed to toggle workflow activation:", error);
      } finally {
        setIsTogglingActivation(false);
      }
    },
    [
      currentWorkflow,
      fetchWorkflows,
      invalidateCache,
      mode,
      setCurrentWorkflow,
      setIsActivated,
      setIsTogglingActivation,
      updateInStore,
    ],
  );
  const handleRegenerateSteps = useCallback(
    async (
      instruction: string = "Generate alternative workflow approach",
      forceDifferentTools: boolean = true,
    ) => {
      if (mode !== "edit" || !currentWorkflow) return;
      trackEvent(ANALYTICS_EVENTS.WORKFLOWS_STEPS_REGENERATED, {
        workflow_id: currentWorkflow.id,
        instruction_length: instruction.length,
        force_different_tools: forceDifferentTools,
        previous_step_count: currentWorkflow.steps?.length || 0,
      });
      setIsRegeneratingSteps(true);
      setRegenerationError(null);
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
        if (result.workflow) {
          setCurrentWorkflow(result.workflow);
          toast.success("Steps regenerated successfully!", {
            description: `${result.workflow.steps?.length || 0} new steps created`,
            duration: 3000,
          });
        }
        if (onWorkflowSaved) onWorkflowSaved(currentWorkflow.id);
        invalidateCache();
        await fetchWorkflows();
        setIsRegeneratingSteps(false);
      } catch (error) {
        const errorMessage =
          error instanceof Error
            ? error.message
            : "Failed to regenerate workflow steps";
        setRegenerationError(errorMessage);
        setIsRegeneratingSteps(false);
      }
    },
    [
      currentWorkflow,
      fetchWorkflows,
      invalidateCache,
      mode,
      onWorkflowSaved,
      selectedIntegrationSlugs,
      setCurrentWorkflow,
      setIsRegeneratingSteps,
      setRegenerationError,
    ],
  );
  const handlePublishToggle = useCallback(async () => {
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
      invalidateCache();
      await fetchWorkflows();
    } catch (error) {
      console.error("Error publishing/unpublishing workflow:", error);
    }
  }, [
    currentWorkflow,
    fetchWorkflows,
    invalidateCache,
    router,
    setCurrentWorkflow,
  ]);
  const handleMarketplaceView = useCallback(() => {
    if (!currentWorkflow?.slug) return;
    router.push(`/use-cases/${currentWorkflow.slug}`);
  }, [currentWorkflow?.slug, router]);
  const handleRegenerateWithReason = useCallback(
    (instructionKey: string) => {
      const reason = REGENERATION_REASONS.find((r) => r.key === instructionKey);
      if (reason) handleRegenerateSteps(reason.instruction, true);
    },
    [handleRegenerateSteps],
  );
  const handleRunWorkflow = useCallback(async () => {
    if (mode !== "edit" || !existingWorkflow) return;
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
      selectWorkflow(existingWorkflow, { autoSend: true });
    } catch (error) {
      console.error("Failed to select workflow for execution:", error);
    }
  }, [currentWorkflow?.steps, existingWorkflow, mode, selectWorkflow]);
  const getButtonText = useCallback(() => {
    if (mode === "edit") return isCreating ? "Saving..." : "Save";
    if (createAndSend) return isCreating ? "Creating..." : "Create and Send";
    return isCreating ? "Creating..." : "Create Workflow";
  }, [mode, isCreating, createAndSend]);
  const handleInitialGeneration = useCallback(() => {
    handleRegenerateSteps("Generate workflow steps", false);
  }, [handleRegenerateSteps]);
  return {
    handleCreate,
    handleUpdate,
    handleSave,
    handleResetToDefault,
    handleDelete,
    confirmDelete,
    handleActivationToggle,
    handlePublishToggle,
    handleMarketplaceView,
    handleRegenerateWithReason,
    handleRunWorkflow,
    getButtonText,
    handleInitialGeneration,
  };
}

function useWorkflowModalHotkeys({
  isOpen,
  creationPhase,
  mode,
  isSaveDisabled,
  handleClose,
  handleSave,
  handleSubmit,
}: {
  isOpen: boolean;
  creationPhase: string;
  mode: string;
  isSaveDisabled: () => boolean;
  handleClose: () => void;
  handleSave: (data: WorkflowFormData) => Promise<void>;
  handleSubmit: (fn: (data: WorkflowFormData) => Promise<void>) => () => void;
}) {
  useHotkeys(
    "escape",
    () => {
      if (isOpen && creationPhase === "form") handleClose();
    },
    { enableOnFormTags: true, enabled: isOpen && creationPhase === "form" },
    [isOpen, creationPhase, handleClose],
  );
  useHotkeys(
    "mod+enter",
    () => {
      if (
        isOpen &&
        creationPhase === "form" &&
        mode !== "preview" &&
        !isSaveDisabled()
      ) {
        handleSubmit(handleSave)();
      }
    },
    {
      enableOnFormTags: true,
      enabled: isOpen && creationPhase === "form" && mode !== "preview",
    },
    [isOpen, creationPhase, isSaveDisabled, mode, handleSubmit, handleSave],
  );
}

interface WorkflowFormColumnProps {
  mode: "create" | "edit" | "preview";
  control: Control<WorkflowFormData>;
  errors: FieldErrors<WorkflowFormData>;
  currentWorkflow: Workflow | null;
  isActivated: boolean;
  isTogglingActivation: boolean;
  missingIntegrations: Integration[];
  connectingId: string | null;
  onConnect: (id: string) => void;
  onToggleActivation: (activated: boolean) => void;
  formData: WorkflowFormData;
  selectedIntegrationSlugs: string[];
  setValue: UseFormSetValue<WorkflowFormData>;
  onDelete: () => void;
  onResetToDefault: () => void;
  onPublishToggle: () => void;
  onMarketplaceView: () => void;
}

function WorkflowFormColumn({
  mode,
  control,
  errors,
  currentWorkflow,
  isActivated,
  isTogglingActivation,
  missingIntegrations,
  connectingId,
  onConnect,
  onToggleActivation,
  formData,
  selectedIntegrationSlugs,
  setValue,
  onDelete,
  onResetToDefault,
  onPublishToggle,
  onMarketplaceView,
}: WorkflowFormColumnProps) {
  const handleActiveTabChange = (tab: "manual" | "schedule" | "trigger") => {
    setValue("activeTab", tab);
  };
  return (
    <div className="flex min-h-0 shrink-0 flex-col lg:flex-1 lg:shrink lg:overflow-hidden">
      <fieldset
        disabled={mode === "preview"}
        className="contents disabled:cursor-default"
      >
        <div className="scrollbar-hover space-y-8 pb-6 lg:min-h-0 lg:flex-1 lg:overflow-y-auto lg:pr-3">
          <MissingIntegrationsAlert
            missingIntegrations={missingIntegrations}
            connectingId={connectingId}
            onConnect={onConnect}
          />
          <WorkflowHeader
            mode={mode}
            control={control}
            errors={errors}
            currentWorkflow={currentWorkflow}
            isActivated={isActivated}
            needsSetup={missingIntegrations.length > 0}
            isTogglingActivation={isTogglingActivation}
            onToggleActivation={onToggleActivation}
            isPublic={!!currentWorkflow?.is_public}
            onUnpublish={onPublishToggle}
            onViewMarketplace={
              currentWorkflow?.slug ? onMarketplaceView : undefined
            }
            onDelete={onDelete}
            onResetToDefault={onResetToDefault}
          />
          <WorkflowDescriptionField
            control={control}
            errors={errors}
            setValue={setValue}
            isPreview={mode === "preview"}
            selectedIntegrationSlugs={selectedIntegrationSlugs}
          />
          <WorkflowTriggerSection
            activeTab={formData.activeTab}
            selectedTrigger={formData.selectedTrigger}
            triggerConfig={formData.trigger_config}
            onActiveTabChange={handleActiveTabChange}
            onSelectedTriggerChange={(trigger) =>
              setValue("selectedTrigger", trigger)
            }
            onTriggerConfigChange={(config) =>
              setValue("trigger_config", config)
            }
            isPreview={mode === "preview"}
          />
          <div className="flex items-center justify-between gap-4 pb-1 pt-2">
            <div className="flex flex-col gap-0.5">
              <span className="text-sm font-medium text-zinc-200">
                Notify when runs finish
              </span>
              <span className="text-xs text-zinc-500">
                GAIA shares the result in your channels after each run
              </span>
            </div>
            <Switch
              size="sm"
              isSelected={formData.notify_on_completion}
              onValueChange={(enabled) =>
                setValue("notify_on_completion", enabled, {
                  shouldDirty: true,
                })
              }
              isDisabled={mode === "preview"}
              aria-label="Notify when runs finish"
            />
          </div>
        </div>
      </fieldset>
    </div>
  );
}

interface WorkflowSidePanelsProps {
  mode: "create" | "edit" | "preview";
  hasPredefinedSteps: boolean;
  predefinedSteps?: PublicWorkflowStep[];
  existingWorkflow?: Workflow | null;
  currentWorkflow: Workflow | null;
  isGeneratingSteps: boolean;
  isRegeneratingSteps: boolean;
  regenerationError: string | null;
  onRegenerateWithReason: (key: string) => void;
  onInitialGeneration: () => void;
  onClearError: () => void;
  isPreview: boolean;
}

function WorkflowSidePanels({
  mode,
  hasPredefinedSteps,
  predefinedSteps,
  existingWorkflow,
  currentWorkflow,
  isGeneratingSteps,
  isRegeneratingSteps,
  regenerationError,
  onRegenerateWithReason,
  onInitialGeneration,
  onClearError,
  isPreview,
}: WorkflowSidePanelsProps) {
  if (mode === "create" && hasPredefinedSteps) {
    return (
      <div className="flex min-h-0 shrink-0 flex-col lg:w-[22rem] lg:pb-6">
        <WorkflowStepsPreviewCard
          steps={(predefinedSteps ?? []).map((step) => ({
            id: step.id ?? "",
            title: step.title,
            description: step.description,
            category: step.category,
          }))}
        />
      </div>
    );
  }
  if ((mode === "edit" || mode === "preview") && existingWorkflow) {
    return (
      <fieldset
        disabled={mode === "preview"}
        className="flex min-h-0 shrink-0 flex-col disabled:cursor-default lg:w-88 lg:pb-6"
      >
        <WorkflowRightPanel
          workflow={currentWorkflow}
          workflowId={existingWorkflow.id}
          isGenerating={isGeneratingSteps}
          isRegenerating={isRegeneratingSteps}
          regenerationError={regenerationError}
          onRegenerateWithReason={onRegenerateWithReason}
          onInitialGeneration={onInitialGeneration}
          onClearError={onClearError}
          isPreview={isPreview}
        />
      </fieldset>
    );
  }
  return null;
}

interface WorkflowFooterAreaProps {
  mode: "create" | "edit" | "preview";
  existingWorkflow?: Workflow | null;
  currentWorkflow: Workflow | null;
  isCreating: boolean;
  modifierKeyName: "command" | "ctrl" | "shift" | "option" | "alt";
  getButtonText: () => string;
  isSaveDisabled: () => boolean;
  onSave: () => void;
  onClose: () => void;
  onRunWorkflow: () => void;
  onPublishToggle: () => void;
}

function WorkflowFooterArea({
  mode,
  existingWorkflow,
  currentWorkflow,
  isCreating,
  modifierKeyName,
  getButtonText,
  isSaveDisabled,
  onSave,
  onClose,
  onRunWorkflow,
  onPublishToggle,
}: WorkflowFooterAreaProps) {
  return (
    <div className="shrink-0">
      <Divider className="bg-zinc-700" />
      <div className="px-6 py-4">
        {mode === "preview" ? (
          <PreviewFooter onClose={onClose} />
        ) : (
          <WorkflowFooter
            existingWorkflow={!!existingWorkflow}
            hasSteps={
              !!currentWorkflow?.steps && currentWorkflow.steps.length > 0
            }
            onRunWorkflow={onRunWorkflow}
            onCancel={onClose}
            onSave={onSave}
            isSaveDisabled={isSaveDisabled()}
            isCreating={isCreating}
            modifierKeyName={modifierKeyName}
            buttonText={getButtonText()}
            isPublic={!!currentWorkflow?.is_public}
            onPublish={onPublishToggle}
          />
        )}
      </div>
    </div>
  );
}

export default function WorkflowModal({
  isOpen,
  onOpenChange,
  onWorkflowSaved,
  onWorkflowDeleted,
  mode,
  existingWorkflow,
  draftData,
  predefinedSteps,
  createAndSend = false,
}: WorkflowModalProps) {
  const hasPredefinedSteps = !!predefinedSteps && predefinedSteps.length > 0;
  const isTwoColumn = mode !== "create" || hasPredefinedSteps;
  const {
    isCreating,
    error: creationError,
    createWorkflow,
    clearError: clearCreationError,
  } = useWorkflowCreation();
  const { selectWorkflow } = useWorkflowSelection();
  const {
    addWorkflow: addToStore,
    updateWorkflow: updateInStore,
    removeWorkflow: removeFromStore,
    fetchWorkflows,
    invalidateCache,
  } = useWorkflowsStore();
  const {
    creationPhase,
    isGeneratingSteps,
    isRegeneratingSteps,
    isTogglingActivation,
    regenerationError,
    isActivated,
    setCreationPhase,
    setIsRegeneratingSteps,
    setIsTogglingActivation,
    setRegenerationError,
    setIsActivated,
    resetToForm,
  } = useWorkflowModalStore();
  const router = useRouter();
  const [isDeleteConfirmOpen, setIsDeleteConfirmOpen] = useState(false);
  const [currentWorkflow, setCurrentWorkflow] = useState<Workflow | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const { data: triggerSchemas } = useTriggerSchemas();
  const { integrations, connectIntegration } = useIntegrations();
  const [connectingId, setConnectingId] = useState<string | null>(null);
  const form = useForm<WorkflowFormData>({
    resolver: zodResolver(workflowFormSchema),
    defaultValues: getDefaultFormValues(),
  });
  const {
    control,
    handleSubmit,
    reset: resetFormValues,
    setValue,
    watch,
    formState: { errors },
  } = form;
  const formData = watch();
  useWorkflowModalSync({
    isOpen,
    mode,
    currentWorkflow,
    existingWorkflow,
    draftData,
    triggerSchemas,
    resetFormValues,
    setIsActivated,
    setCreationPhase,
    setCurrentWorkflow,
    clearCreationError,
    resetToForm,
  });
  const {
    selectedIntegrationSlugs,
    missingTriggerIntegration,
    missingIntegrations,
  } = useWorkflowDerivedIntegrations({
    formData,
    integrations,
    triggerSchemas,
    currentWorkflow,
    existingWorkflow,
  });
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
  const { modifierKeyName } = usePlatform();
  const { isSaveDisabled } = useWorkflowFormGuards({
    formData,
    mode,
    existingWorkflow,
    selectedIntegrationSlugs,
    isCreating,
    missingTriggerIntegration,
  });
  const handleClose = useCallback(() => {
    onOpenChange(false);
  }, [onOpenChange]);
  const {
    handleSave,
    handleResetToDefault,
    handleDelete,
    confirmDelete,
    handleActivationToggle,
    handlePublishToggle,
    handleMarketplaceView,
    handleRegenerateWithReason,
    handleRunWorkflow,
    getButtonText,
    handleInitialGeneration,
  } = useWorkflowModalActions({
    mode,
    currentWorkflow,
    setCurrentWorkflow,
    existingWorkflow,
    hasPredefinedSteps,
    predefinedSteps,
    selectedIntegrationSlugs,
    createWorkflow,
    setCreationPhase,
    addToStore,
    updateInStore,
    removeFromStore,
    fetchWorkflows,
    invalidateCache,
    onWorkflowSaved,
    onWorkflowDeleted,
    selectWorkflow,
    createAndSend,
    handleClose,
    setIsDeleteConfirmOpen,
    setIsDeleting,
    setIsRegeneratingSteps,
    setRegenerationError,
    setIsTogglingActivation,
    setIsActivated,
    isCreating,
    router,
  });
  useWorkflowModalHotkeys({
    isOpen,
    creationPhase,
    mode,
    isSaveDisabled,
    handleClose,
    handleSave,
    handleSubmit,
  });
  return (
    <>
      <Modal
        isOpen={isOpen}
        onOpenChange={onOpenChange}
        hideCloseButton
        size={isTwoColumn ? "5xl" : "4xl"}
        className={
          isTwoColumn
            ? "h-[85vh] max-h-208 max-w-6xl bg-secondary-bg"
            : "max-h-[90vh] bg-secondary-bg"
        }
        backdrop="blur"
      >
        <ModalContent>
          <ModalBody className="flex min-h-0 flex-col gap-0 p-0">
            {creationPhase === "form" ? (
              <>
                <div className="scrollbar-hover flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto px-6 pt-6 lg:flex-row lg:gap-8 lg:overflow-hidden">
                  <WorkflowFormColumn
                    mode={mode}
                    control={control}
                    errors={errors}
                    currentWorkflow={currentWorkflow}
                    isActivated={isActivated}
                    isTogglingActivation={isTogglingActivation}
                    missingIntegrations={missingIntegrations}
                    connectingId={connectingId}
                    onConnect={handleConnectIntegration}
                    onToggleActivation={(newActivated) =>
                      handleActivationToggle(newActivated, missingIntegrations)
                    }
                    formData={formData}
                    selectedIntegrationSlugs={selectedIntegrationSlugs}
                    setValue={setValue}
                    onDelete={handleDelete}
                    onResetToDefault={handleResetToDefault}
                    onPublishToggle={handlePublishToggle}
                    onMarketplaceView={handleMarketplaceView}
                  />
                  <WorkflowSidePanels
                    mode={mode}
                    hasPredefinedSteps={hasPredefinedSteps}
                    predefinedSteps={predefinedSteps}
                    existingWorkflow={existingWorkflow}
                    currentWorkflow={currentWorkflow}
                    isGeneratingSteps={isGeneratingSteps}
                    isRegeneratingSteps={isRegeneratingSteps}
                    regenerationError={regenerationError}
                    onRegenerateWithReason={handleRegenerateWithReason}
                    onInitialGeneration={handleInitialGeneration}
                    onClearError={() => setRegenerationError(null)}
                    isPreview={mode === "preview"}
                  />
                </div>
                <WorkflowFooterArea
                  mode={mode}
                  existingWorkflow={existingWorkflow}
                  currentWorkflow={currentWorkflow}
                  isCreating={isCreating}
                  modifierKeyName={modifierKeyName}
                  getButtonText={getButtonText}
                  isSaveDisabled={isSaveDisabled}
                  onSave={() => handleSubmit(handleSave)()}
                  onClose={handleClose}
                  onRunWorkflow={handleRunWorkflow}
                  onPublishToggle={handlePublishToggle}
                />
              </>
            ) : (
              <div className="px-6 py-4">
                <WorkflowLoadingState
                  phase={creationPhase}
                  mode={mode}
                  error={creationError}
                  workflow={currentWorkflow}
                  onClose={handleClose}
                  onRetry={() => setCreationPhase("form")}
                />
              </div>
            )}
          </ModalBody>
        </ModalContent>
      </Modal>
      {mode === "edit" && existingWorkflow && (
        <ConfirmationDialog
          isOpen={isDeleteConfirmOpen}
          title="Delete workflow"
          message={`Are you sure you want to delete "${existingWorkflow.title}"? This action cannot be undone.`}
          confirmText="Delete"
          cancelText="Cancel"
          variant="destructive"
          isLoading={isDeleting}
          onConfirm={confirmDelete}
          onCancel={() => setIsDeleteConfirmOpen(false)}
        />
      )}
    </>
  );
}

function PreviewFooter({ onClose }: { onClose: () => void }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div className="flex items-center gap-2 text-xs text-zinc-400">
        <InformationCircleIcon height={16} className="shrink-0 text-zinc-500" />
        <span>
          You can customise every detail later from the Workflows page.
        </span>
      </div>
      <Button color="primary" onPress={onClose}>
        Close
      </Button>
    </div>
  );
}

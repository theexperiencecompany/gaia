"use client";

import { Button } from "@heroui/button";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import { zodResolver } from "@hookform/resolvers/zod";
import { InformationCircleIcon } from "@icons";
import { useCallback, useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { useHotkeys } from "react-hotkeys-hook";
import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import WorkflowDescriptionField from "@/features/workflows/components/workflow-modal/WorkflowDescriptionField";
import WorkflowFooter from "@/features/workflows/components/workflow-modal/WorkflowFooter";
import WorkflowHeader from "@/features/workflows/components/workflow-modal/WorkflowHeader";
import WorkflowLoadingState from "@/features/workflows/components/workflow-modal/WorkflowLoadingState";
import WorkflowRightPanel from "@/features/workflows/components/workflow-modal/WorkflowRightPanel";
import WorkflowTriggerSection from "@/features/workflows/components/workflow-modal/WorkflowTriggerSection";
import { useWorkflowCreation } from "@/features/workflows/hooks/useWorkflowCreation";
import { usePlatform } from "@/hooks/ui/usePlatform";
import { useRouter } from "@/i18n/navigation";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { toast } from "@/lib/toast";
import type { WorkflowDraftData } from "@/types/features/toolDataTypes";
import { type Workflow, workflowApi } from "../api/workflowApi";
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

import { findTriggerSchema, getTriggerDisplayInfo } from "../triggers/utils";
import { getBrowserTimezone } from "../utils/browserTimezone";

interface WorkflowModalProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onWorkflowSaved?: (workflowId: string) => void;
  onWorkflowDeleted?: (workflowId: string) => void;
  mode: "create" | "edit" | "preview";
  existingWorkflow?: Workflow | null;
  /** Pre-fill form from AI-generated draft data */
  draftData?: WorkflowDraftData | null;
}

export default function WorkflowModal({
  isOpen,
  onOpenChange,
  onWorkflowSaved,
  onWorkflowDeleted,
  mode,
  existingWorkflow,
  draftData,
}: WorkflowModalProps) {
  const {
    isCreating,
    error: creationError,
    createWorkflow,
    clearError: clearCreationError,
  } = useWorkflowCreation();

  const { selectWorkflow } = useWorkflowSelection();

  // Get workflows store actions for optimistic updates
  const {
    addWorkflow: addToStore,
    updateWorkflow: updateInStore,
    removeWorkflow: removeFromStore,
    fetchWorkflows,
  } = useWorkflowsStore();

  // Zustand UI state
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

  // Single source of truth for workflow data
  const [currentWorkflow, setCurrentWorkflow] = useState<Workflow | null>(null);

  // Selected integration slugs for hinting step generation
  const [selectedIntegrationSlugs, setSelectedIntegrationSlugs] = useState<
    string[]
  >([]);

  // Fetch trigger schemas for slug normalization
  const { data: triggerSchemas } = useTriggerSchemas();

  const { integrations, connectIntegration } = useIntegrations();
  const [isConnecting, setIsConnecting] = useState(false);
  const missingIntegration = (() => {
    if (!currentWorkflow) return null;
    if (currentWorkflow.trigger_config.type !== "integration") return null;
    const display = getTriggerDisplayInfo(
      currentWorkflow,
      integrations,
      triggerSchemas,
    );
    if (!display.integration) return null;
    if (display.integration.status === "connected") return null;
    return display.integration;
  })();
  const handleConnectMissingIntegration = useCallback(async () => {
    if (!missingIntegration || isConnecting) return;
    setIsConnecting(true);
    try {
      await connectIntegration(missingIntegration.id);
    } catch (err) {
      console.error("Failed to connect integration", err);
    } finally {
      setIsConnecting(false);
    }
  }, [missingIntegration, isConnecting, connectIntegration]);

  // React Hook Form setup
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

  // Manage the single workflow state from all sources
  useEffect(() => {
    if (existingWorkflow) {
      setCurrentWorkflow(existingWorkflow);
      setSelectedIntegrationSlugs(existingWorkflow.selected_integrations ?? []);
    } else {
      setCurrentWorkflow(null);
      setSelectedIntegrationSlugs([]);
    }
  }, [existingWorkflow]);

  // Watch form data for change detection
  const formData = watch();

  // Platform detection for keyboard shortcuts
  const { modifierKeyName } = usePlatform();

  // Check if save button should be disabled (used for hotkey and button)
  const isSaveDisabled = useCallback(() => {
    if (!formData.title.trim() || !formData.prompt?.trim()) {
      return true;
    }

    if (
      formData.activeTab === "schedule" &&
      formData.trigger_config.type === "schedule" &&
      !formData.trigger_config.cron_expression
    ) {
      // Schedule tab requires cron expression
      return true;
    }

    if (formData.activeTab === "trigger" && !formData.selectedTrigger) {
      // Trigger tab requires a trigger to be selected
      return true;
    }

    if (
      isIntegrationTrigger(formData.trigger_config) &&
      !hasValidTriggerName(formData.trigger_config)
    ) {
      // Integration triggers MUST have a valid trigger_name
      return true;
    }

    if (mode === "edit" && !hasFormChanges()) {
      // Edit mode requires changes
      return true;
    }

    if (isCreating) {
      // Block while creating
      return true;
    }

    return false;
  }, [formData, mode, isCreating, existingWorkflow]);

  // Keyboard shortcut: Escape to close modal
  useHotkeys(
    "escape",
    () => {
      if (isOpen && creationPhase === "form") {
        handleClose();
      }
    },
    { enableOnFormTags: true, enabled: isOpen && creationPhase === "form" },
    [isOpen, creationPhase],
  );

  // Keyboard shortcut: Mod+Enter to save
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
    [isOpen, creationPhase, isSaveDisabled, mode],
  );

  // Handle initial step generation (for empty workflows)
  const handleInitialGeneration = () => {
    handleRegenerateSteps("Generate workflow steps", false); // Don't force different tools for initial generation
  };

  // Initialize form data based on mode and currentWorkflow
  useEffect(() => {
    if ((mode === "edit" || mode === "preview") && currentWorkflow) {
      const formValues = workflowToFormData(currentWorkflow);
      resetFormValues(formValues);
      // Initialize activation state from current workflow
      setIsActivated(currentWorkflow.activated);
      // Reset to form phase for edit mode
      setCreationPhase("form");
      return;
    }

    // Handle draft data from AI-generated workflow
    if (mode === "create" && draftData) {
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
          timezone: getBrowserTimezone(),
        };
      } else if (
        draftData.trigger_type === "integration" &&
        draftData.trigger_slug
      ) {
        // Normalize trigger_slug: backend may return composio_slug, frontend needs slug
        const schema = findTriggerSchema(
          triggerSchemas,
          draftData.trigger_slug,
        );
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

      resetFormValues({
        title: draftData.suggested_title,
        description: draftData.suggested_description || undefined,
        prompt: draftData.prompt || draftData.suggested_description || "",
        activeTab,
        selectedTrigger: selectedTriggerValue,
        trigger_config: triggerConfig,
      });
      setIsActivated(true);
      setCreationPhase("form");
      return;
    }

    // Reset to default for create mode
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

  // Check if form has actual changes for edit mode
  const hasFormChanges = () => {
    if (mode === "create") return true;

    if (!existingWorkflow) return true;

    const currentFormData = workflowToFormData(existingWorkflow);

    const persistedSlugs = [...(existingWorkflow.selected_integrations ?? [])]
      .sort((a, b) => a.localeCompare(b))
      .join(",");
    const currentSlugs = [...selectedIntegrationSlugs]
      .sort((a, b) => a.localeCompare(b))
      .join(",");

    return (
      formData.title !== currentFormData.title ||
      formData.description !== currentFormData.description ||
      formData.prompt !== currentFormData.prompt ||
      formData.activeTab !== currentFormData.activeTab ||
      formData.selectedTrigger !== currentFormData.selectedTrigger ||
      JSON.stringify(formData.trigger_config) !==
        JSON.stringify(currentFormData.trigger_config) ||
      persistedSlugs !== currentSlugs
    );
  };

  const handleFormReset = () => {
    resetFormValues(getDefaultFormValues());
    setSelectedIntegrationSlugs([]);
    resetToForm();
    clearCreationError();
  };

  const handleSave = async (data: WorkflowFormData) => {
    if (!data.title.trim() || !data.prompt?.trim()) return;

    if (mode === "create") {
      setCreationPhase("creating");

      // Validate the trigger config before sending
      try {
        const validationResult = workflowFormSchema.safeParse(data);
        if (!validationResult.success) {
          setCreationPhase("error");
          return;
        }
      } catch {
        setCreationPhase("error");
        return;
      }

      // Create the request object that matches the backend API
      const createRequest = {
        title: data.title,
        description: data.description || undefined,
        prompt: data.prompt,
        trigger_config: data.trigger_config,
        generate_immediately: true, // Generate steps immediately
        selected_integrations:
          selectedIntegrationSlugs.length > 0
            ? selectedIntegrationSlugs
            : undefined,
      };

      const result = await createWorkflow(createRequest);

      if (result.success && result.workflow) {
        trackEvent(ANALYTICS_EVENTS.WORKFLOWS_CREATED, {
          workflow_id: result.workflow.id,
          workflow_title: result.workflow.title,
          step_count: result.workflow.steps?.length || 0,
          trigger_type: data.trigger_config.type,
          has_schedule: data.trigger_config.type === "schedule",
        });

        // Update currentWorkflow with the newly created workflow
        setCurrentWorkflow(result.workflow);
        setCreationPhase("success");

        // Show success toast
        toast.success("Workflow created successfully!", {
          description: `${result.workflow.steps?.length || 0} steps generated`,
          duration: 3000,
        });

        // Optimistic update: add to store immediately for instant UI feedback
        addToStore(result.workflow);

        // Notify parent callbacks if provided (for backwards compatibility)
        if (onWorkflowSaved) onWorkflowSaved(result.workflow.id);
        await fetchWorkflows();

        handleClose();
      } else {
        setCreationPhase("error");
      }
      return;
    }
    // Edit mode - update the existing workflow
    if (!currentWorkflow) return;

    try {
      const updateRequest = {
        title: data.title,
        description: data.description || undefined,
        prompt: data.prompt,
        trigger_config: {
          ...data.trigger_config,
        },
        selected_integrations: selectedIntegrationSlugs,
      };

      // Decide if step regeneration is needed BEFORE persisting,
      // so the comparison runs against the previous truth.
      const previousFormData = workflowToFormData(currentWorkflow);
      const previousSlugs = [...(currentWorkflow.selected_integrations ?? [])]
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

      if (updatedWorkflow) {
        setCurrentWorkflow({
          ...currentWorkflow,
          ...updateRequest,
          description: updateRequest.description ?? "",
        });
      }

      updateInStore(currentWorkflow.id, updateRequest);

      if (stepRelevantChanged) {
        // Modal stays open with a visible regen indicator until the user
        // dismisses it.
        setIsRegeneratingSteps(true);
        setRegenerationError(null);
        try {
          const regenResult = await workflowApi.regenerateWorkflowSteps(
            currentWorkflow.id,
            {
              instruction: "Update steps to match the new workflow definition",
              force_different_tools: false,
              selected_integrations:
                selectedIntegrationSlugs.length > 0
                  ? selectedIntegrationSlugs
                  : undefined,
            },
          );

          if (regenResult.workflow) {
            setCurrentWorkflow(regenResult.workflow);
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
          setRegenerationError(message);
          toast.error("Saved, but failed to regenerate steps", {
            description: message,
          });
        } finally {
          setIsRegeneratingSteps(false);
        }
      } else {
        toast.success("Workflow updated", { duration: 3000 });
      }

      if (onWorkflowSaved) onWorkflowSaved(currentWorkflow.id);

      await fetchWorkflows();
    } catch (error) {
      console.error("Failed to update workflow:", error);
      toast.error("Failed to save workflow", {
        description:
          error instanceof Error
            ? error.message
            : "An unexpected error occurred",
        duration: 4000,
      });
    }
  };

  const handleClose = () => {
    handleFormReset();
    onOpenChange(false);
  };

  const handleResetToDefault = async () => {
    if (!existingWorkflow?.id) return;
    try {
      await workflowApi.resetToDefault(existingWorkflow.id);
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
  };

  const handleDeleteConfirm = async () => {
    if (mode !== "edit" || !existingWorkflow) return;
    setIsDeleteConfirmOpen(false);
    try {
      trackEvent(ANALYTICS_EVENTS.WORKFLOWS_DELETED, {
        workflow_id: existingWorkflow.id,
        workflow_title: existingWorkflow.title,
        step_count: existingWorkflow.steps?.length || 0,
        is_public: existingWorkflow.is_public,
      });
      await workflowApi.deleteWorkflow(existingWorkflow.id);
      removeFromStore(existingWorkflow.id);
      if (onWorkflowDeleted) onWorkflowDeleted(existingWorkflow.id);
      await fetchWorkflows();
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
    }
  };

  // Handle activation toggle
  const handleActivationToggle = async (newActivated: boolean) => {
    if (mode !== "edit" || !currentWorkflow) return;

    setIsTogglingActivation(true);
    try {
      if (newActivated) {
        await workflowApi.activateWorkflow(currentWorkflow.id);
      } else {
        await workflowApi.deactivateWorkflow(currentWorkflow.id);
      }

      // Update currentWorkflow activation state
      setCurrentWorkflow({
        ...currentWorkflow,
        activated: newActivated,
      });
      setIsActivated(newActivated);
      updateInStore(currentWorkflow.id, { activated: newActivated });
      await fetchWorkflows();
    } catch (error) {
      console.error("Failed to toggle workflow activation:", error);
    } finally {
      setIsTogglingActivation(false);
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
      workflow_title: currentWorkflow.title,
      instruction,
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
          selected_integrations:
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
      await fetchWorkflows();

      setIsRegeneratingSteps(false);
    } catch (error) {
      console.error("Failed to regenerate workflow steps:", error);
      const errorMessage =
        error instanceof Error
          ? error.message
          : "Failed to regenerate workflow steps";
      setRegenerationError(errorMessage);
      setIsRegeneratingSteps(false);
    }
  };

  const handlePublishToggle = async () => {
    if (!currentWorkflow?.id) return;
    try {
      if (currentWorkflow.is_public) {
        trackEvent(ANALYTICS_EVENTS.WORKFLOWS_UNPUBLISHED, {
          workflow_id: currentWorkflow.id,
          workflow_title: currentWorkflow.title,
        });
        await workflowApi.unpublishWorkflow(currentWorkflow.id);
        setCurrentWorkflow({ ...currentWorkflow, is_public: false });
      } else {
        trackEvent(ANALYTICS_EVENTS.WORKFLOWS_PUBLISHED, {
          workflow_id: currentWorkflow.id,
          workflow_title: currentWorkflow.title,
          step_count: currentWorkflow.steps?.length || 0,
        });
        const result = await workflowApi.publishWorkflow(currentWorkflow.id);
        const slug = result.slug ?? currentWorkflow.slug;
        setCurrentWorkflow({ ...currentWorkflow, is_public: true, slug });
        if (slug) router.push(`/use-cases/${slug}`);
      }
      await fetchWorkflows();
    } catch (error) {
      console.error("Error publishing/unpublishing workflow:", error);
    }
  };

  const handleMarketplaceView = () => {
    if (!currentWorkflow?.slug) return;
    router.push(`/use-cases/${currentWorkflow.slug}`);
  };

  // Handle regeneration with specific instruction
  // Keys must match WorkflowStepsPanel regenerationReasons
  const handleRegenerateWithReason = (instructionKey: string) => {
    const regenerationReasons = [
      {
        key: "too_complex",
        label: "Simplify workflow",
        description: "Simplify with fewer steps",
      },
      {
        key: "missing_functionality",
        label: "Add missing functionality",
        description: "Add specific features",
      },
      {
        key: "wrong_tools",
        label: "Use different tools",
        description: "Use different integrations",
      },
      {
        key: "alternative_approach",
        label: "Generate alternative approach",
        description: "Try a completely different strategy",
      },
    ];
    const reason = regenerationReasons.find((r) => r.key === instructionKey);
    if (reason) {
      handleRegenerateSteps(reason.label, true); // Always force different tools for regeneration
    }
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
        workflow_title: existingWorkflow.title,
        step_count: currentWorkflow.steps.length,
        trigger_type: existingWorkflow.trigger_config.type,
      });

      // Close modal first to ensure clean state
      onOpenChange(false);

      // Then navigate after modal starts closing
      // Small delay ensures modal close animation begins and component cleanup doesn't interfere
      setTimeout(() => {
        selectWorkflow(existingWorkflow, { autoSend: true });
      }, 50);
    } catch (error) {
      console.error("Failed to select workflow for execution:", error);
    }
  };

  const getButtonText = () => {
    if (mode === "edit") return isCreating ? "Saving..." : "Save";
    return isCreating ? "Creating..." : "Create Workflow";
  };

  // Handle tab change for trigger section
  const handleActiveTabChange = (tab: "manual" | "schedule" | "trigger") => {
    setValue("activeTab", tab);
  };

  return (
    <>
      <Modal
        isOpen={isOpen}
        onOpenChange={(open) => {
          if (!open) handleFormReset();
          onOpenChange(open);
        }}
        // isDismissable={false}
        hideCloseButton
        size={mode === "create" ? "3xl" : "4xl"}
        className={`max-h-[71vh] bg-secondary-bg ${mode !== "create" ? "min-w-[80vw]" : ""}`}
        backdrop="blur"
      >
        <ModalContent>
          <ModalBody className="min-h-0 overflow-hidden pr-2">
            {creationPhase === "form" ? (
              <div className="flex min-h-0 flex-1 gap-8">
                <div className="flex min-h-0 flex-1 flex-col">
                  <fieldset
                    disabled={mode === "preview"}
                    className="contents disabled:cursor-default"
                  >
                    <div className="min-h-0 flex-1 space-y-5 overflow-y-auto ">
                      {missingIntegration && (
                        <div className="flex items-center justify-between gap-3 rounded-2xl bg-amber-400/10 px-3 py-2.5 text-sm text-amber-300">
                          <span>
                            This workflow is disabled because{" "}
                            <span className="font-medium">
                              {missingIntegration.name}
                            </span>{" "}
                            isn't connected. Connect it to start running.
                          </span>
                          <Button
                            color="primary"
                            size="sm"
                            isLoading={isConnecting}
                            onPress={handleConnectMissingIntegration}
                          >
                            Connect {missingIntegration.name}
                          </Button>
                        </div>
                      )}
                      <WorkflowHeader
                        mode={mode}
                        control={control}
                        errors={errors}
                        currentWorkflow={currentWorkflow}
                        isActivated={isActivated}
                        isTogglingActivation={isTogglingActivation}
                        onToggleActivation={handleActivationToggle}
                        isPublic={!!currentWorkflow?.is_public}
                        onUnpublish={handlePublishToggle}
                        onDelete={() => setIsDeleteConfirmOpen(true)}
                        onResetToDefault={handleResetToDefault}
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

                      <div>
                        <div className="border-t border-zinc-800 mb-2" />
                        <div className="space-y-4">
                          <WorkflowDescriptionField
                            control={control}
                            errors={errors}
                            setValue={setValue}
                            mode={mode === "preview" ? "edit" : mode}
                            isPreview={mode === "preview"}
                            selectedIntegrationSlugs={selectedIntegrationSlugs}
                            onIntegrationSlugsChange={
                              setSelectedIntegrationSlugs
                            }
                          />
                        </div>
                      </div>
                    </div>
                  </fieldset>

                  {mode === "preview" ? (
                    <PreviewFooter onClose={handleClose} />
                  ) : (
                    <WorkflowFooter
                      existingWorkflow={!!existingWorkflow}
                      hasSteps={
                        !!currentWorkflow?.steps &&
                        currentWorkflow.steps.length > 0
                      }
                      onRunWorkflow={handleRunWorkflow}
                      onCancel={handleClose}
                      onSave={() => handleSubmit(handleSave)()}
                      isSaveDisabled={isSaveDisabled()}
                      isCreating={isCreating}
                      modifierKeyName={modifierKeyName}
                      buttonText={getButtonText()}
                      isPublic={!!currentWorkflow?.is_public}
                      onPublishToggle={handlePublishToggle}
                      onViewMarketplace={
                        currentWorkflow?.slug
                          ? handleMarketplaceView
                          : undefined
                      }
                    />
                  )}
                </div>

                {(mode === "edit" || mode === "preview") &&
                  existingWorkflow && (
                    <fieldset
                      disabled={mode === "preview"}
                      className="contents disabled:cursor-default"
                    >
                      <WorkflowRightPanel
                        workflow={currentWorkflow}
                        workflowId={existingWorkflow.id}
                        isGenerating={isGeneratingSteps}
                        isRegenerating={isRegeneratingSteps}
                        regenerationError={regenerationError}
                        onRegenerateWithReason={handleRegenerateWithReason}
                        onInitialGeneration={handleInitialGeneration}
                        onClearError={() => setRegenerationError(null)}
                        isPreview={mode === "preview"}
                      />
                    </fieldset>
                  )}
              </div>
            ) : (
              <WorkflowLoadingState
                phase={creationPhase}
                mode={mode}
                error={creationError}
                workflow={currentWorkflow}
                onClose={handleClose}
                onRetry={() => setCreationPhase("form")}
              />
            )}
          </ModalBody>
        </ModalContent>
      </Modal>

      <Modal
        isOpen={isDeleteConfirmOpen}
        onOpenChange={setIsDeleteConfirmOpen}
        size="sm"
        backdrop="blur"
      >
        <ModalContent>
          <ModalHeader>Delete workflow?</ModalHeader>
          <ModalBody>
            <p className="text-sm text-foreground-500">
              <span className="font-medium text-foreground">
                {currentWorkflow?.title}
              </span>{" "}
              will be permanently deleted. This cannot be undone.
            </p>
          </ModalBody>
          <ModalFooter>
            <Button
              variant="flat"
              onPress={() => setIsDeleteConfirmOpen(false)}
            >
              Cancel
            </Button>
            <Button color="danger" onPress={handleDeleteConfirm}>
              Delete
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </>
  );
}

function PreviewFooter({ onClose }: { onClose: () => void }) {
  return (
    <div className="mt-6 pt-4 pb-3">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-start gap-2 rounded-2xl bg-zinc-800 px-3 py-2.5 text-xs text-zinc-300">
          <InformationCircleIcon
            height={16}
            className="mt-0.5 shrink-0 text-zinc-400"
          />
          <span>
            Don't worry, you can customise all the details later from the
            Workflows page.
          </span>
        </div>
        <Button color="primary" onPress={onClose}>
          Close
        </Button>
      </div>
    </div>
  );
}

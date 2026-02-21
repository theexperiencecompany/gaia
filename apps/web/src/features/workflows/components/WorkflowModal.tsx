"use client";

import { Modal, ModalBody, ModalContent } from "@heroui/modal";
import { zodResolver } from "@hookform/resolvers/zod";
import { useCallback, useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { useHotkeys } from "react-hotkeys-hook";
import { toast } from "sonner";
import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
import { usePlatform } from "@/hooks/ui/usePlatform";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import type { WorkflowDraftData } from "@/types/features/toolDataTypes";

import { type Workflow, workflowApi } from "../api/workflowApi";
import { useWorkflowCreation } from "../hooks";
import {
  getBrowserTimezone,
  getDefaultFormValues,
  type WorkflowFormData,
  workflowFormSchema,
  workflowToFormData,
} from "../schemas/workflowFormSchema";
import { useWorkflowModalStore } from "../stores/workflowModalStore";
import { useWorkflowsStore } from "../stores/workflowsStore";
import {
  createDefaultTriggerConfig,
  findTriggerSchema,
  useTriggerSchemas,
} from "../triggers";
import { hasValidTriggerName, isIntegrationTrigger } from "../triggers/types";
import {
  WorkflowDescriptionField,
  WorkflowFooter,
  WorkflowHeader,
  WorkflowLoadingState,
  WorkflowRightPanel,
  WorkflowTriggerSection,
} from "./workflow-modal";

interface WorkflowModalProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onWorkflowSaved?: (workflowId: string) => void;
  onWorkflowDeleted?: (workflowId: string) => void;
  mode: "create" | "edit";
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

  // Single source of truth for workflow data
  const [currentWorkflow, setCurrentWorkflow] = useState<Workflow | null>(null);

  // Fetch trigger schemas for slug normalization
  const { data: triggerSchemas } = useTriggerSchemas();

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
    } else {
      setCurrentWorkflow(null);
    }
  }, [existingWorkflow]);

  // Watch form data for change detection
  const formData = watch();

  // Platform detection for keyboard shortcuts
  const { modifierKeyName } = usePlatform();

  // Check if save button should be disabled (used for hotkey and button)
  const isSaveDisabled = useCallback(() => {
    if (!formData.title.trim() || !formData.description.trim()) {
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
      if (isOpen && creationPhase === "form" && !isSaveDisabled()) {
        handleSubmit(handleSave)();
      }
    },
    { enableOnFormTags: true, enabled: isOpen && creationPhase === "form" },
    [isOpen, creationPhase, isSaveDisabled],
  );

  // Handle initial step generation (for empty workflows)
  const handleInitialGeneration = () => {
    handleRegenerateSteps("Generate workflow steps", false); // Don't force different tools for initial generation
  };

  // Initialize form data based on mode and currentWorkflow
  useEffect(() => {
    if (mode === "edit" && currentWorkflow) {
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
        draftData.trigger_type === "scheduled"
          ? "schedule"
          : draftData.trigger_type === "integration"
            ? "trigger"
            : "manual";

      let triggerConfig: WorkflowFormData["trigger_config"];
      let selectedTriggerValue = "";

      if (draftData.trigger_type === "scheduled") {
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
        description: draftData.prompt || draftData.suggested_description,
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

    return (
      formData.title !== currentFormData.title ||
      formData.description !== currentFormData.description ||
      formData.activeTab !== currentFormData.activeTab ||
      formData.selectedTrigger !== currentFormData.selectedTrigger ||
      JSON.stringify(formData.trigger_config) !==
        JSON.stringify(currentFormData.trigger_config)
    );
  };

  const handleFormReset = () => {
    resetFormValues(getDefaultFormValues());
    resetToForm();
    clearCreationError();
  };

  const handleSave = async (data: WorkflowFormData) => {
    if (!data.title.trim() || !data.description.trim()) return;

    if (mode === "create") {
      setCreationPhase("creating");

      // Log the request for debugging
      console.log("Creating workflow with data:", data);

      // Validate the trigger config before sending
      try {
        const validationResult = workflowFormSchema.safeParse(data);
        if (!validationResult.success) {
          console.error("Form validation failed:", validationResult.error);
          setCreationPhase("error");
          return;
        }
        console.log("Form validation passed");
      } catch (validationError) {
        console.error("Form validation error:", validationError);
        setCreationPhase("error");
        return;
      }

      // Create the request object that matches the backend API
      const createRequest = {
        title: data.title,
        description: data.description,
        trigger_config: data.trigger_config,
        generate_immediately: true, // Generate steps immediately
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
        description: data.description,
        trigger_config: {
          ...data.trigger_config,
        },
      };

      const updatedWorkflow = await workflowApi.updateWorkflow(
        currentWorkflow.id,
        updateRequest,
      );

      // Update currentWorkflow with the updated data
      if (updatedWorkflow) {
        setCurrentWorkflow({
          ...currentWorkflow,
          ...updateRequest,
        });
      }

      // Optimistic update: update in store immediately
      updateInStore(currentWorkflow.id, updateRequest);

      if (onWorkflowSaved) onWorkflowSaved(currentWorkflow.id);

      await fetchWorkflows();
      handleClose();
    } catch (error) {
      console.error("Failed to update workflow:", error);
    }
  };

  const handleClose = () => {
    handleFormReset();
    onOpenChange(false);
  };

  const handleDelete = async () => {
    if (mode === "edit" && existingWorkflow) {
      try {
        trackEvent(ANALYTICS_EVENTS.WORKFLOWS_DELETED, {
          workflow_id: existingWorkflow.id,
          workflow_title: existingWorkflow.title,
          step_count: existingWorkflow.steps?.length || 0,
          is_public: existingWorkflow.is_public,
        });

        // Call the actual delete API
        await workflowApi.deleteWorkflow(existingWorkflow.id);

        // Optimistic update: remove from store immediately
        removeFromStore(existingWorkflow.id);

        if (onWorkflowDeleted) onWorkflowDeleted(existingWorkflow.id);

        await fetchWorkflows();
        handleClose();
      } catch (error) {
        console.error("Failed to delete workflow:", error);
      }
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
        console.log(
          "Workflow selected for manual execution in chat with auto-send",
        );
      }, 50);
    } catch (error) {
      console.error("Failed to select workflow for execution:", error);
    }
  };

  const getButtonText = () => {
    if (mode === "edit") return isCreating ? "Saving..." : "Save Changes";
    return isCreating ? "Creating..." : "Create Workflow";
  };

  // Handle tab change for trigger section
  const handleActiveTabChange = (tab: "manual" | "schedule" | "trigger") => {
    setValue("activeTab", tab);
  };

  return (
    <Modal
      key={currentWorkflow?.id || "new-workflow"}
      isOpen={isOpen}
      onOpenChange={(open) => {
        if (!open) handleFormReset();
        onOpenChange(open);
      }}
      isDismissable={false}
      hideCloseButton
      size={mode === "create" ? "3xl" : "4xl"}
      className={`max-h-[70vh] bg-secondary-bg ${mode !== "create" ? "min-w-[80vw]" : ""}`}
      backdrop="blur"
    >
      <ModalContent>
        <ModalBody className="max-h-full space-y-6 overflow-hidden pr-2">
          {creationPhase === "form" ? (
            <div className="flex h-full min-h-0 items-start gap-8">
              <div className="flex min-h-0 flex-1 flex-col">
                <div className="min-h-0 flex-1 space-y-6 overflow-y-auto">
                  <WorkflowHeader
                    mode={mode}
                    control={control}
                    errors={errors}
                    currentWorkflow={currentWorkflow}
                    onWorkflowChange={setCurrentWorkflow}
                    onDelete={handleDelete}
                    onRefetchWorkflows={fetchWorkflows}
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
                  />

                  <div className="border-t border-zinc-800" />

                  <div className="space-y-4 flex-1 h-full">
                    <WorkflowDescriptionField
                      control={control}
                      errors={errors}
                      mode={mode}
                    />
                  </div>
                </div>

                <WorkflowFooter
                  mode={mode}
                  existingWorkflow={!!existingWorkflow}
                  isActivated={isActivated}
                  isTogglingActivation={isTogglingActivation}
                  onToggleActivation={handleActivationToggle}
                  hasSteps={
                    !!currentWorkflow?.steps && currentWorkflow.steps.length > 0
                  }
                  onRunWorkflow={handleRunWorkflow}
                  onCancel={handleClose}
                  onSave={() => handleSubmit(handleSave)()}
                  isSaveDisabled={isSaveDisabled()}
                  isCreating={isCreating}
                  modifierKeyName={modifierKeyName}
                  buttonText={getButtonText()}
                />
              </div>

              {mode === "edit" && existingWorkflow && (
                <WorkflowRightPanel
                  workflow={currentWorkflow}
                  workflowId={existingWorkflow.id}
                  isGenerating={isGeneratingSteps}
                  isRegenerating={isRegeneratingSteps}
                  regenerationError={regenerationError}
                  onRegenerateWithReason={handleRegenerateWithReason}
                  onInitialGeneration={handleInitialGeneration}
                  onClearError={() => setRegenerationError(null)}
                />
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
  );
}

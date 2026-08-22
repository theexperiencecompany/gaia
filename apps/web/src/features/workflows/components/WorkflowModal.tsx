"use client";

import { Modal, ModalBody, ModalContent } from "@heroui/modal";
import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { useHotkeys } from "react-hotkeys-hook";
import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import { useWorkflowModalActions } from "@/features/workflows/components/workflow-modal/useWorkflowModalActions";
import { useWorkflowSaveGate } from "@/features/workflows/components/workflow-modal/useWorkflowSaveGate";
import WorkflowLoadingState from "@/features/workflows/components/workflow-modal/WorkflowLoadingState";
import WorkflowModalFormView from "@/features/workflows/components/workflow-modal/WorkflowModalFormView";
import { usePlatform } from "@/hooks/ui/usePlatform";
import { getUserHomeTimezone } from "@/lib/timezone";
import type { WorkflowDraftData } from "@/types/features/toolDataTypes";
import type { PublicWorkflowStep } from "@/types/features/workflowTypes";
import type { Workflow } from "../api/workflowApi";
import {
  getDefaultFormValues,
  type WorkflowFormData,
  workflowFormSchema,
  workflowToFormData,
} from "../schemas/workflowFormSchema";
import { useWorkflowModalStore } from "../stores/workflowModalStore";
import { useTriggerSchemas } from "../triggers/hooks/useTriggerSchemas";
import { createDefaultTriggerConfig } from "../triggers/registry";
import { findTriggerSchema } from "../triggers/utils";

interface WorkflowModalProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onWorkflowSaved?: (workflowId: string) => void;
  onWorkflowDeleted?: (workflowId: string) => void;
  mode: "create" | "edit" | "preview";
  existingWorkflow?: Workflow | null;
  /** Pre-fill form from AI-generated draft data */
  draftData?: WorkflowDraftData | null;
  /**
   * Pre-built steps from a public/community workflow. When provided:
   * - the steps are forwarded to create so the backend skips regeneration
   * - the integration chip selector is hidden
   * - a read-only preview panel renders alongside the form
   */
  predefinedSteps?: PublicWorkflowStep[];
  /**
   * When true, the create button shows "Create and Send" and the workflow is
   * immediately executed in the chat after creation.
   */
  createAndSend?: boolean;
}

// Build the initial form values for a create-mode modal seeded from an
// AI-generated draft, normalizing its trigger into the form's shape.
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
    // Normalize trigger_slug: backend may return composio_slug, frontend needs slug
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
    // A draft carries no icon; the form picks the default for its category.
    icon: null,
    icon_color: null,
    activeTab,
    selectedTrigger: selectedTriggerValue,
    trigger_config: triggerConfig,
    notify_on_completion: true,
  };
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
  // Two-column (form + side panel) for edit/preview and community-step create;
  // plain create is a single comfortable column.
  const isTwoColumn = mode !== "create" || hasPredefinedSteps;

  // Single source of truth for workflow data
  const [currentWorkflow, setCurrentWorkflow] = useState<Workflow | null>(null);

  // Fetch trigger schemas for slug normalization
  const { data: triggerSchemas } = useTriggerSchemas();

  // Zustand UI state read for rendering
  const {
    creationPhase,
    isGeneratingSteps,
    isRegeneratingSteps,
    isTogglingActivation,
    regenerationError,
    isActivated,
    setCreationPhase,
    setIsActivated,
    setRegenerationError,
    resetToForm,
  } = useWorkflowModalStore();

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

  // Watch form data for change detection
  const formData = watch();

  const handleClose = () => {
    // Reset is handled by the close-animation effect — calling it here would
    // blank the form while the modal is still visibly fading out.
    onOpenChange(false);
  };

  // All mutating actions plus their loading flags and derived integration data
  const actions = useWorkflowModalActions({
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
  });

  // Defer the form reset until after the modal's exit animation finishes —
  // resetting synchronously on close blanks out the visible form fields while
  // the modal is still fading out, which reads as an abrupt close. The delay
  // matches HeroUI's modal exit transition.
  useEffect(() => {
    if (isOpen) return;
    const timer = globalThis.setTimeout(() => {
      // Only clear the form fields here — NOT the creation phase. Resetting the
      // phase to "form" mid-fade would flash the form/button view over the
      // terminal "success" screen on the way out. The phase is reset on open.
      resetFormValues(getDefaultFormValues());
    }, 250);
    return () => globalThis.clearTimeout(timer);
  }, [isOpen, resetFormValues]);

  // Reset the creation phase to a clean "form" when the modal OPENS (false ->
  // true transition only), so each session starts fresh without flashing the
  // previous session's success/error screen during the close animation. The ref
  // guard is essential: resetToForm/clearCreationError identities are unstable,
  // so without it this synchronous reset re-runs every render and infinite-loops.
  const wasOpenRef = useRef(false);
  useEffect(() => {
    if (isOpen && !wasOpenRef.current) {
      console.debug("[workflow:modal] opened -> resetting creation phase", {
        mode,
      });
      resetToForm();
      actions.clearCreationError();
    }
    wasOpenRef.current = isOpen;
  }, [isOpen, resetToForm, actions.clearCreationError, mode]);

  // Sync the local working copy from the prop only when a DIFFERENT workflow is
  // passed (modal opens / switches workflow). A background list refetch (e.g.
  // after save/regenerate) re-passes the SAME workflow with possibly-stale
  // steps; syncing on every object change would clobber freshly-regenerated
  // steps and flash the old ones. currentWorkflow is the edit-session truth.
  // Adjusting during render (instead of in an effect) lets React discard the
  // stale frame before anything paints.
  const [syncedWorkflowId, setSyncedWorkflowId] = useState<string | null>(null);
  const nextWorkflowId = existingWorkflow?.id ?? null;
  if (nextWorkflowId !== syncedWorkflowId) {
    setSyncedWorkflowId(nextWorkflowId);
    setCurrentWorkflow(existingWorkflow ?? null);
  }

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
      resetFormValues(buildDraftFormValues(draftData, triggerSchemas));
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

  // Save-readiness rules (change detection + disabled state)
  const { isSaveDisabled } = useWorkflowSaveGate({
    mode,
    existingWorkflow,
    formData,
    selectedIntegrationSlugs: actions.selectedIntegrationSlugs,
    missingTriggerIntegration: actions.missingTriggerIntegration,
    isCreating: actions.isCreating,
  });

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
        handleSubmit(actions.handleSave)();
      }
    },
    {
      enableOnFormTags: true,
      enabled: isOpen && creationPhase === "form" && mode !== "preview",
    },
    [isOpen, creationPhase, isSaveDisabled, mode],
  );

  const getButtonText = () => {
    if (mode === "edit") return actions.isCreating ? "Saving..." : "Save";
    if (createAndSend)
      return actions.isCreating ? "Creating..." : "Create and Send";
    return actions.isCreating ? "Creating..." : "Create Workflow";
  };

  // Platform detection for keyboard shortcuts
  const { modifierKeyName } = usePlatform();

  return (
    <>
      <Modal
        isOpen={isOpen}
        onOpenChange={onOpenChange}
        hideCloseButton
        size={isTwoColumn ? "5xl" : "4xl"}
        // Two-column mode uses a definite height so the side panel's
        // flex/overflow chain (h-full → min-h-0 → overflow-y-auto) resolves
        // and the Steps panel doesn't clip.
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
              <WorkflowModalFormView
                mode={mode}
                formData={formData}
                control={control}
                errors={errors}
                setValue={setValue}
                currentWorkflow={currentWorkflow}
                existingWorkflow={existingWorkflow ?? null}
                activation={{
                  isActive: isActivated,
                  isToggling: isTogglingActivation,
                }}
                missingIntegrations={actions.missingIntegrations}
                connectingId={actions.connectingId}
                onConnect={actions.handleConnectIntegration}
                selectedIntegrationSlugs={actions.selectedIntegrationSlugs}
                onActivationToggle={actions.handleActivationToggle}
                onPublishToggle={actions.handlePublishToggle}
                onViewMarketplace={actions.handleMarketplaceView}
                onDelete={actions.handleDelete}
                onResetToDefault={actions.handleResetToDefault}
                steps={{
                  hasPredefined: hasPredefinedSteps,
                  isGenerating: isGeneratingSteps,
                  isRegenerating: isRegeneratingSteps,
                }}
                predefinedSteps={predefinedSteps}
                regenerationError={regenerationError}
                onRegenerateWithReason={actions.handleRegenerateWithReason}
                onInitialGeneration={actions.handleInitialGeneration}
                onClearError={() => setRegenerationError(null)}
                modifierKeyName={modifierKeyName}
                buttonText={getButtonText()}
                save={{
                  isDisabled: isSaveDisabled(),
                  isCreating: actions.isCreating,
                }}
                onRunWorkflow={actions.handleRunWorkflow}
                onSubmit={() => handleSubmit(actions.handleSave)()}
                onClose={handleClose}
              />
            ) : (
              <div className="px-6 py-4">
                <WorkflowLoadingState
                  phase={creationPhase}
                  mode={mode}
                  error={actions.creationError}
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
          isOpen={actions.isDeleteConfirmOpen}
          title="Delete workflow"
          message={`Are you sure you want to delete "${existingWorkflow.title}"? This action cannot be undone.`}
          confirmText="Delete"
          cancelText="Cancel"
          variant="destructive"
          isLoading={actions.isDeleting}
          onConfirm={actions.confirmDelete}
          onCancel={() => actions.setIsDeleteConfirmOpen(false)}
        />
      )}
    </>
  );
}

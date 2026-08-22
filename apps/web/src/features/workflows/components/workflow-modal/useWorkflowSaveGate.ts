"use client";

import { useCallback } from "react";

import type { Integration } from "@/features/integrations/types";

import type { Workflow } from "../../api/workflowApi";
import {
  type WorkflowFormData,
  workflowToFormData,
} from "../../schemas/workflowFormSchema";
import {
  hasValidTriggerName,
  isIntegrationTrigger,
} from "../../triggers/types";

interface UseWorkflowSaveGateParams {
  mode: "create" | "edit" | "preview";
  existingWorkflow?: Workflow | null;
  /** Live form values (react-hook-form watch()) */
  formData: WorkflowFormData;
  selectedIntegrationSlugs: string[];
  missingTriggerIntegration: Integration | null;
  isCreating: boolean;
}

/**
 * Save-readiness rules for the workflow modal: whether the form differs from
 * the persisted workflow and whether the save/create button must be disabled.
 * Extracted from WorkflowModal alongside the action hook.
 */
export function useWorkflowSaveGate({
  mode,
  existingWorkflow,
  formData,
  selectedIntegrationSlugs,
  missingTriggerIntegration,
  isCreating,
}: UseWorkflowSaveGateParams) {
  // Check if form has actual changes for edit mode
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

    if (missingTriggerIntegration) {
      // Don't create/save a workflow whose trigger integration isn't connected
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
  }, [formData, mode, missingTriggerIntegration, isCreating, hasFormChanges]);

  return { hasFormChanges, isSaveDisabled };
}

"use client";

import { Button } from "@heroui/button";
import { Divider } from "@heroui/divider";
import { Switch } from "@heroui/switch";
import { InformationCircleIcon } from "@icons";
import type { Control, FieldErrors, UseFormSetValue } from "react-hook-form";

import type { Integration } from "@/features/integrations/types";
import type { PublicWorkflowStep } from "@/types/features/workflowTypes";
import type { Workflow } from "../../api/workflowApi";
import type { WorkflowFormData } from "../../schemas/workflowFormSchema";
import { MissingIntegrationsAlert } from "../shared/WorkflowCardComponents";
import WorkflowDescriptionField from "./WorkflowDescriptionField";
import WorkflowFooter from "./WorkflowFooter";
import WorkflowHeader from "./WorkflowHeader";
import WorkflowRightPanel from "./WorkflowRightPanel";
import WorkflowStepsPreviewCard from "./WorkflowStepsPreviewCard";
import WorkflowTriggerSection from "./WorkflowTriggerSection";

type ModifierKeyName = "command" | "ctrl" | "shift" | "option" | "alt";

/** Activation badge state shown by the workflow header */
interface WorkflowActivationState {
  isActive: boolean;
  isToggling: boolean;
}

/** Steps availability + generation/regeneration activity for the side panels */
interface WorkflowStepsState {
  /** Pre-built community steps shown as a read-only side panel */
  hasPredefined: boolean;
  isGenerating: boolean;
  isRegenerating: boolean;
}

/** Save button state for the footer */
interface WorkflowSaveState {
  isDisabled: boolean;
  isCreating: boolean;
}

interface WorkflowModalFormViewProps {
  mode: "create" | "edit" | "preview";
  /** Live form values (react-hook-form watch()) */
  formData: WorkflowFormData;
  control: Control<WorkflowFormData>;
  errors: FieldErrors<WorkflowFormData>;
  setValue: UseFormSetValue<WorkflowFormData>;
  currentWorkflow: Workflow | null;
  existingWorkflow: Workflow | null;
  activation: WorkflowActivationState;
  missingIntegrations: Integration[];
  connectingId: string | null;
  onConnect: (integrationId: string) => void;
  /** @-mentioned integration slugs from the prompt (persisted with the workflow) */
  selectedIntegrationSlugs: string[];
  onActivationToggle: (activated: boolean) => void;
  onPublishToggle: () => void;
  onViewMarketplace: () => void;
  onDelete: () => void;
  onResetToDefault: () => void;
  steps: WorkflowStepsState;
  predefinedSteps?: PublicWorkflowStep[];
  regenerationError: string | null;
  onRegenerateWithReason: (instructionKey: string) => void;
  onInitialGeneration: () => void;
  onClearError: () => void;
  // Footer
  modifierKeyName: ModifierKeyName;
  buttonText: string;
  save: WorkflowSaveState;
  onRunWorkflow: () => void;
  /** Parent-wired form submit (handleSubmit(handleSave)) */
  onSubmit: () => void;
  onClose: () => void;
}

/**
 * The modal's "form" phase: left form column, right steps/history panel and
 * the footer. Extracted from WorkflowModal so the parent stays focused on
 * state, effects and action wiring.
 */
export default function WorkflowModalFormView({
  mode,
  formData,
  control,
  errors,
  setValue,
  currentWorkflow,
  existingWorkflow,
  activation,
  missingIntegrations,
  connectingId,
  onConnect,
  selectedIntegrationSlugs,
  onActivationToggle,
  onPublishToggle,
  onViewMarketplace,
  onDelete,
  onResetToDefault,
  steps,
  predefinedSteps,
  regenerationError,
  onRegenerateWithReason,
  onInitialGeneration,
  onClearError,
  modifierKeyName,
  buttonText,
  save,
  onRunWorkflow,
  onSubmit,
  onClose,
}: WorkflowModalFormViewProps) {
  const isPreview = mode === "preview";

  return (
    <>
      <div className="scrollbar-hover flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto px-6 pt-6 lg:flex-row lg:gap-8 lg:overflow-hidden">
        {/* Form column — the single scroll region on desktop. Below
            lg the row stacks and scrolls as a whole, so the column
            keeps its full content height (shrink-0) instead of being
            compressed by the fixed row height and overflowing onto the
            panel below. lg:flex-1 restores fill-and-scroll on desktop. */}
        <div className="flex min-h-0 shrink-0 flex-col lg:flex-1 lg:shrink lg:overflow-hidden">
          <fieldset
            disabled={isPreview}
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
                isActivated={activation.isActive}
                needsSetup={missingIntegrations.length > 0}
                isTogglingActivation={activation.isToggling}
                onToggleActivation={onActivationToggle}
                isPublic={!!currentWorkflow?.is_public}
                onUnpublish={onPublishToggle}
                onViewMarketplace={
                  currentWorkflow?.slug ? onViewMarketplace : undefined
                }
                onDelete={onDelete}
                onResetToDefault={onResetToDefault}
              />

              <WorkflowDescriptionField
                control={control}
                errors={errors}
                setValue={setValue}
                isPreview={isPreview}
                selectedIntegrationSlugs={selectedIntegrationSlugs}
              />

              <WorkflowTriggerSection
                activeTab={formData.activeTab}
                selectedTrigger={formData.selectedTrigger}
                triggerConfig={formData.trigger_config}
                onActiveTabChange={(tab) => setValue("activeTab", tab)}
                onSelectedTriggerChange={(trigger) =>
                  setValue("selectedTrigger", trigger)
                }
                onTriggerConfigChange={(config) =>
                  setValue("trigger_config", config)
                }
                isPreview={isPreview}
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
                  isDisabled={isPreview}
                  aria-label="Notify when runs finish"
                />
              </div>
            </div>
          </fieldset>
        </div>

        {/* Side panel — predefined steps preview */}
        {mode === "create" && steps.hasPredefined && (
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
        )}

        {/* Side panel — steps + history (edit / preview).
            The column stretches to the row's (now definite) height and
            the panel fills it via h-full, scrolling internally — so
            switching Steps↔History can't resize the modal. `lg:pb-6`
            matches the form column's bottom breathing room. */}
        {(mode === "edit" || mode === "preview") && existingWorkflow && (
          <fieldset
            disabled={isPreview}
            className="flex min-h-0 shrink-0 flex-col disabled:cursor-default lg:w-88 lg:pb-6"
          >
            <WorkflowRightPanel
              workflow={currentWorkflow}
              workflowId={existingWorkflow.id}
              isGenerating={steps.isGenerating}
              isRegenerating={steps.isRegenerating}
              regenerationError={regenerationError}
              onRegenerateWithReason={onRegenerateWithReason}
              onInitialGeneration={onInitialGeneration}
              onClearError={onClearError}
              isPreview={isPreview}
            />
          </fieldset>
        )}
      </div>

      {/* Full-width footer */}
      <div className="shrink-0">
        <Divider className="bg-zinc-700" />
        <div className="px-6 py-4">
          {mode === "preview" ? (
            <PreviewFooter onClose={onClose} />
          ) : (
            <WorkflowFooter
              workflow={{
                isExisting: !!existingWorkflow,
                hasSteps:
                  !!currentWorkflow?.steps && currentWorkflow.steps.length > 0,
                isPublic: !!currentWorkflow?.is_public,
              }}
              save={{
                isDisabled: save.isDisabled,
                isCreating: save.isCreating,
                buttonText: buttonText,
              }}
              modifierKeyName={modifierKeyName}
              onRunWorkflow={onRunWorkflow}
              onCancel={onClose}
              onSave={onSubmit}
              onPublish={onPublishToggle}
            />
          )}
        </div>
      </div>
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

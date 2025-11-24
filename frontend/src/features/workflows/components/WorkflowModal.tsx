"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/dropdown";
import { Input, Textarea } from "@heroui/input";
import { Modal, ModalBody, ModalContent } from "@heroui/modal";
import { Select, SelectItem } from "@heroui/select";
import { Skeleton } from "@heroui/skeleton";
import { Switch } from "@heroui/switch";
import { Tab, Tabs } from "@heroui/tabs";
import { Tooltip } from "@heroui/tooltip";
import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";

import CustomSpinner from "@/components/ui/spinner";
import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import {
  AlertCircleIcon,
  ArrowDown01Icon,
  CheckmarkCircle02Icon,
  Delete02Icon,
  InformationCircleIcon,
  LinkSquare02Icon,
  MoreVerticalIcon,
  PlayIcon,
  RedoIcon,
} from "@/icons";
import { posthog } from "@/lib";

import { type Workflow, workflowApi } from "../api/workflowApi";
import { useWorkflowCreation } from "../hooks";
import {
  getDefaultFormValues,
  type WorkflowFormData,
  workflowFormSchema,
  workflowToFormData,
} from "../schemas/workflowFormSchema";
import { useWorkflowModalStore } from "../stores/workflowModalStore";
import { getTriggerEnabledIntegrations } from "../utils/triggerDisplay";
import { ScheduleBuilder } from "./ScheduleBuilder";
import WorkflowSteps from "./shared/WorkflowSteps";

interface WorkflowModalProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onWorkflowSaved?: (workflowId: string) => void;
  onWorkflowDeleted?: (workflowId: string) => void;
  onWorkflowListRefresh?: () => void;
  mode: "create" | "edit";
  existingWorkflow?: Workflow | null;
}

export default function WorkflowModal({
  isOpen,
  onOpenChange,
  onWorkflowSaved,
  onWorkflowDeleted,
  onWorkflowListRefresh,
  mode,
  existingWorkflow,
}: WorkflowModalProps) {
  const router = useRouter();
  const {
    isCreating,
    error: creationError,
    createWorkflow,
    clearError: clearCreationError,
  } = useWorkflowCreation();

  const { selectWorkflow } = useWorkflowSelection();
  const { integrations } = useIntegrations();

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

  // Handle initial step generation (for empty workflows)
  const handleInitialGeneration = () => {
    handleRegenerateSteps("Generate workflow steps", false); // Don't force different tools for initial generation
  };

  // Regeneration reason options (only for existing workflows)
  const regenerationReasons = [
    {
      key: "alternative",
      label: "Generate alternative approach",
      description: "Create a different way to achieve the same goal",
    },
    {
      key: "efficient",
      label: "Make more efficient",
      description: "Optimize steps for better performance",
    },
    {
      key: "detailed",
      label: "Add more detail",
      description: "Include more comprehensive steps",
    },
    {
      key: "simplified",
      label: "Simplify workflow",
      description: "Reduce complexity and number of steps",
    },
    {
      key: "tools",
      label: "Use different tools",
      description: "Try different tools for the same tasks",
    },
    {
      key: "reorder",
      label: "Reorder steps",
      description: "Change the sequence of operations",
    },
  ];

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
    // Reset to default for create mode
    resetFormValues(getDefaultFormValues());
    // Reset activation state for create mode
    setIsActivated(true);
    // Reset to form phase for create mode
    setCreationPhase("form");
  }, [
    mode,
    currentWorkflow,
    isOpen,
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
        // Track workflow creation
        posthog.capture("workflows:created", {
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

        if (onWorkflowSaved) onWorkflowSaved(result.workflow.id);
        if (onWorkflowListRefresh) onWorkflowListRefresh();

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

      if (onWorkflowSaved) {
        onWorkflowSaved(currentWorkflow.id);
      }
      // Refresh workflow list after update
      if (onWorkflowListRefresh) {
        onWorkflowListRefresh();
      }
      handleClose();
    } catch (error) {
      console.error("Failed to update workflow:", error);
    }
  };

  const handleClose = () => {
    resetFormValues(getDefaultFormValues());
    onOpenChange(false);
  };

  const handleDelete = async () => {
    if (mode === "edit" && existingWorkflow) {
      try {
        // Track workflow deletion
        posthog.capture("workflows:deleted", {
          workflow_id: existingWorkflow.id,
          workflow_title: existingWorkflow.title,
          step_count: existingWorkflow.steps?.length || 0,
          is_public: existingWorkflow.is_public,
        });

        // Call the actual delete API
        await workflowApi.deleteWorkflow(existingWorkflow.id);

        if (onWorkflowDeleted) {
          onWorkflowDeleted(existingWorkflow.id);
        }
        // Refresh workflow list after deletion
        if (onWorkflowListRefresh) {
          onWorkflowListRefresh();
        }
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

      // Refresh workflow list after activation/deactivation
      if (onWorkflowListRefresh) {
        onWorkflowListRefresh();
      }
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

    // Track workflow regeneration
    posthog.capture("workflows:steps_regenerated", {
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
      if (onWorkflowListRefresh) onWorkflowListRefresh();

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
  const handleRegenerateWithReason = (instructionKey: string) => {
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
      // Track workflow run
      posthog.capture("workflows:executed", {
        workflow_id: existingWorkflow.id,
        workflow_title: existingWorkflow.title,
        step_count: currentWorkflow.steps.length,
        trigger_type: existingWorkflow.trigger_config.type,
      });

      selectWorkflow(existingWorkflow, { autoSend: true });

      // Close the modal after navigation starts
      onOpenChange(false);

      console.log(
        "Workflow selected for manual execution in chat with auto-send",
      );
    } catch (error) {
      console.error("Failed to select workflow for execution:", error);
    }
  };

  const renderTriggerTab = () => {
    const triggerOptions = getTriggerEnabledIntegrations(integrations);
    const selectedTriggerOption = triggerOptions.find(
      (t) => t.id === formData.selectedTrigger,
    );

    return (
      <div className="w-full">
        <div className="w-full">
          <Select
            aria-label="Choose a custom trigger for your workflow"
            placeholder="Choose a trigger for your workflow"
            fullWidth
            className="w-screen max-w-xl"
            selectedKeys={
              formData.selectedTrigger ? [formData.selectedTrigger] : []
            }
            onSelectionChange={(keys) => {
              const selectedTrigger = Array.from(keys)[0] as string;
              setValue("selectedTrigger", selectedTrigger);

              // Update trigger config based on selection
              if (selectedTrigger === "gmail") {
                setValue("trigger_config", {
                  type: "email",
                  enabled: true,
                });
              } else {
                setValue("trigger_config", {
                  type: "manual",
                  enabled: true,
                });
              }
            }}
            startContent={
              selectedTriggerOption &&
              getToolCategoryIcon(selectedTriggerOption.id, {
                width: 20,
                height: 20,
                showBackground: false,
              })
            }
          >
            {triggerOptions.map((trigger) => (
              <SelectItem
                key={trigger.id}
                textValue={trigger.name}
                startContent={getToolCategoryIcon(trigger.id, {
                  width: 20,
                  height: 20,
                  showBackground: false,
                })}
                description={trigger.description}
              >
                {trigger.name}
              </SelectItem>
            ))}
          </Select>
        </div>

        {selectedTriggerOption && (
          <div className="mt-4 max-w-xl space-y-4">
            <p className="px-1 text-xs text-zinc-500">
              {selectedTriggerOption.description}
            </p>
          </div>
        )}
      </div>
    );
  };

  const renderManualTab = () => (
    <div className="w-full">
      <p className="text-sm text-zinc-500">
        This workflow will be triggered manually when you run it.
      </p>
    </div>
  );

  const renderScheduleTab = () => (
    <div className="w-full">
      <ScheduleBuilder
        value={
          formData.trigger_config.type === "schedule"
            ? formData.trigger_config.cron_expression || ""
            : ""
        }
        onChange={(cronExpression) => {
          if (formData.trigger_config.type === "schedule") {
            setValue("trigger_config", {
              ...formData.trigger_config,
              cron_expression: cronExpression,
            });
          }
        }}
      />
    </div>
  );

  const getButtonText = () => {
    if (mode === "edit") return isCreating ? "Saving..." : "Save Changes";
    return isCreating ? "Creating..." : "Create Workflow";
  };

  return (
    <Modal
      key={currentWorkflow?.id || "new-workflow"}
      isOpen={isOpen}
      onOpenChange={(open) => {
        if (!open) handleFormReset();
        onOpenChange(open);
      }}
      hideCloseButton
      size={mode === "create" ? "3xl" : "4xl"}
      className={`max-h-[70vh] ${mode !== "create" ? "min-w-[80vw]" : ""}`}
      backdrop="blur"
    >
      <ModalContent>
        <ModalBody className="max-h-full space-y-6 overflow-hidden pr-2">
          {creationPhase === "form" ? (
            <div className="flex h-full min-h-0 gap-8">
              <div className="flex min-h-0 flex-1 flex-col">
                <div className="min-h-0 flex-1 space-y-6 overflow-y-auto">
                  <div className="flex items-center gap-3 pt-5">
                    <Controller
                      name="title"
                      control={control}
                      render={({ field }) => (
                        <Input
                          {...field}
                          autoFocus
                          placeholder={
                            mode === "edit"
                              ? "Edit workflow name"
                              : "Enter workflow name"
                          }
                          variant="underlined"
                          classNames={{
                            input: "font-medium! text-4xl",
                            inputWrapper: "px-0",
                          }}
                          isRequired
                          className="flex-1"
                          isInvalid={!!errors.title}
                          errorMessage={errors.title?.message}
                        />
                      )}
                    />

                    {/* Action dropdown for edit mode */}
                    {mode === "edit" && (
                      <Dropdown placement="bottom-end" className="max-w-100">
                        <DropdownTrigger>
                          <Button variant="flat" size="sm" isIconOnly>
                            <MoreVerticalIcon />
                          </Button>
                        </DropdownTrigger>
                        <DropdownMenu>
                          <DropdownItem
                            key="publish"
                            startContent={
                              <PlayIcon className="relative top-1 h-4 w-4" />
                            }
                            classNames={{
                              description: "text-wrap",
                              base: "items-start!",
                            }}
                            description={
                              currentWorkflow?.is_public
                                ? "Remove from community marketplace"
                                : "Share to community marketplace"
                            }
                            onPress={async () => {
                              if (!currentWorkflow?.id) return;

                              try {
                                if (currentWorkflow.is_public) {
                                  posthog.capture("workflows:unpublished", {
                                    workflow_id: currentWorkflow.id,
                                    workflow_title: currentWorkflow.title,
                                  });
                                  await workflowApi.unpublishWorkflow(
                                    currentWorkflow.id,
                                  );
                                  setCurrentWorkflow((prev) =>
                                    prev ? { ...prev, is_public: false } : null,
                                  );
                                } else {
                                  posthog.capture("workflows:published", {
                                    workflow_id: currentWorkflow.id,
                                    workflow_title: currentWorkflow.title,
                                    step_count:
                                      currentWorkflow.steps?.length || 0,
                                  });
                                  await workflowApi.publishWorkflow(
                                    currentWorkflow.id,
                                  );
                                  setCurrentWorkflow((prev) =>
                                    prev ? { ...prev, is_public: true } : null,
                                  );
                                }
                              } catch (error) {
                                console.error(
                                  "Error publishing/unpublishing workflow:",
                                  error,
                                );
                              }
                            }}
                          >
                            {currentWorkflow?.is_public
                              ? "Unpublish Workflow"
                              : "Publish Workflow"}
                          </DropdownItem>

                          {/* Conditionally render marketplace item */}
                          {currentWorkflow?.is_public ? (
                            <DropdownItem
                              key="marketplace"
                              startContent={
                                <LinkSquare02Icon className="h-4 w-4" />
                              }
                              classNames={{
                                description: "text-wrap",
                                base: "items-start!",
                              }}
                              description="Open community marketplace"
                              onPress={() => {
                                router.push("/use-cases#community-section");
                              }}
                            >
                              View on Marketplace
                            </DropdownItem>
                          ) : (
                            <></>
                          )}

                          <DropdownItem
                            key="delete"
                            color="danger"
                            startContent={<Delete02Icon className="h-4 w-4" />}
                            classNames={{
                              description: "text-wrap",
                              base: "items-start!",
                            }}
                            description="Permanently delete this workflow"
                            onPress={handleDelete}
                          >
                            Delete Workflow
                          </DropdownItem>
                        </DropdownMenu>
                      </Dropdown>
                    )}
                  </div>

                  {/* Trigger/Schedule Configuration */}
                  <div className="space-y-3">
                    <div className="flex items-start gap-3">
                      <div className="mt-2.5 flex min-w-26 items-center justify-between gap-1.5 text-sm font-medium text-zinc-400">
                        <span className="text-nowrap">When to Run</span>
                        <Tooltip
                          content={
                            <div className="px-1 py-2">
                              <p className="text-sm font-medium">When to Run</p>
                              <p className="mt-1 text-xs text-zinc-400">
                                Choose how your workflow will be activated:
                              </p>
                              <ul className="mt-2 space-y-1 text-xs text-zinc-400">
                                <li>
                                  • <span className="font-medium">Manual:</span>{" "}
                                  Run the workflow manually when you need it
                                </li>
                                <li>
                                  •{" "}
                                  <span className="font-medium">Schedule:</span>{" "}
                                  Run at specific times or intervals
                                </li>
                                <li>
                                  •{" "}
                                  <span className="font-medium">Trigger:</span>{" "}
                                  Run when external events occur (coming soon)
                                </li>
                              </ul>
                            </div>
                          }
                          placement="top"
                          delay={500}
                        >
                          <InformationCircleIcon className="h-3.5 w-3.5 cursor-help text-zinc-500 hover:text-zinc-300" />
                        </Tooltip>
                      </div>
                      <div className="w-full">
                        <Tabs
                          color="primary"
                          classNames={{
                            tabList: "flex flex-row",
                            base: "flex items-start",
                            tabWrapper: "w-full",
                            panel: "min-w-full",
                          }}
                          className="w-full"
                          selectedKey={formData.activeTab}
                          onSelectionChange={(key) => {
                            const tabKey = key as
                              | "manual"
                              | "schedule"
                              | "trigger";
                            setValue("activeTab", tabKey);

                            // Set appropriate trigger config based on tab
                            if (tabKey === "schedule") {
                              setValue("trigger_config", {
                                type: "schedule",
                                enabled: true,
                                cron_expression:
                                  formData.trigger_config.type === "schedule"
                                    ? formData.trigger_config.cron_expression
                                    : "0 9 * * *",
                                timezone: "UTC",
                              });
                            } else if (tabKey === "trigger") {
                              setValue("trigger_config", {
                                type: "email",
                                enabled: true,
                              });
                            } else {
                              setValue("trigger_config", {
                                type: "manual",
                                enabled: true,
                              });
                            }
                          }}
                        >
                          <Tab key="schedule" title="Schedule">
                            {renderScheduleTab()}
                          </Tab>
                          <Tab key="trigger" title="Trigger">
                            {renderTriggerTab()}
                          </Tab>
                          <Tab key="manual" title="Manual">
                            {renderManualTab()}
                          </Tab>
                        </Tabs>
                      </div>
                    </div>
                  </div>

                  {/* Separator */}
                  <div className="border-t border-zinc-800" />

                  {/* Description Section */}
                  <div className="space-y-4">
                    <Controller
                      name="description"
                      control={control}
                      render={({ field }) => (
                        <Textarea
                          {...field}
                          placeholder={
                            mode === "edit"
                              ? "Edit workflow description"
                              : "Describe what this workflow should do when triggered"
                          }
                          minRows={4}
                          variant="underlined"
                          className="text-sm"
                          isRequired
                          isInvalid={!!errors.description}
                          errorMessage={errors.description?.message}
                        />
                      )}
                    />
                  </div>
                </div>

                {/* Form Footer */}
                <div className="mt-8 border-t border-zinc-800 pt-6 pb-3">
                  {/* All controls in one row */}
                  <div className="flex items-center justify-between">
                    {/* Left side: Switch and Run Workflow */}
                    <div className="flex items-center gap-4">
                      {existingWorkflow && (
                        <Tooltip
                          content={
                            !currentWorkflow?.steps ||
                            currentWorkflow.steps.length === 0
                              ? "Cannot run workflow without generated steps"
                              : "Manually run workflow"
                          }
                          placement="top"
                        >
                          <Button
                            color="success"
                            variant="flat"
                            startContent={<PlayIcon className="h-4 w-4" />}
                            onPress={handleRunWorkflow}
                            size="sm"
                            isDisabled={
                              !currentWorkflow?.steps ||
                              currentWorkflow.steps.length === 0
                            }
                          >
                            Run Manually
                          </Button>
                        </Tooltip>
                      )}

                      {mode === "edit" && (
                        <div className="flex items-center gap-3">
                          <Tooltip
                            content={
                              isActivated
                                ? "Deactivate this workflow to prevent it from running"
                                : "Activate this workflow to allow it to run"
                            }
                            placement="top"
                          >
                            <Switch
                              isSelected={isActivated}
                              onValueChange={handleActivationToggle}
                              isDisabled={isTogglingActivation}
                              size="sm"
                            />
                          </Tooltip>
                        </div>
                      )}
                    </div>

                    {/* Right side: Cancel and Save */}
                    <div className="flex items-center gap-3">
                      <Button variant="flat" onPress={handleClose}>
                        Cancel
                      </Button>
                      <Button
                        color="primary"
                        onPress={() => handleSubmit(handleSave)()}
                        isLoading={isCreating}
                        isDisabled={
                          !formData.title.trim() ||
                          !formData.description.trim() ||
                          (formData.activeTab === "schedule" &&
                            formData.trigger_config.type === "schedule" &&
                            !formData.trigger_config.cron_expression) ||
                          (mode === "edit" && !hasFormChanges())
                        }
                      >
                        {getButtonText()}
                      </Button>
                    </div>
                  </div>
                </div>
              </div>

              {/* Right side - Workflow Steps */}
              {mode === "edit" && (
                <div className="flex min-h-0 w-96 flex-col space-y-4 rounded-2xl bg-zinc-950/30 p-6">
                  {/* Show regeneration error state */}
                  {regenerationError && (
                    <div className="space-y-4">
                      <div className="flex flex-col items-center justify-center py-8">
                        <div className="text-center">
                          <div className="mb-4">
                            <AlertCircleIcon className="mx-auto h-12 w-12 text-danger" />
                          </div>
                          <h3 className="text-lg font-medium text-danger">
                            Generation Failed
                          </h3>
                          <p className="mb-4 text-sm text-zinc-400">
                            {regenerationError}
                          </p>
                          <Button
                            variant="flat"
                            size="sm"
                            onPress={() => {
                              setRegenerationError(null);
                            }}
                          >
                            Try Again
                          </Button>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Show workflow steps - either existing or newly generated */}
                  {existingWorkflow && !regenerationError && (
                    <>
                      {/* Show steps if they exist */}
                      {currentWorkflow?.steps &&
                      currentWorkflow.steps.length > 0 ? (
                        <>
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <h4 className="font-medium text-zinc-200">
                                Workflow Steps
                              </h4>
                              <Chip
                                size="sm"
                                color="primary"
                                className="text-sm font-medium"
                              >
                                {currentWorkflow.steps.length}
                              </Chip>
                            </div>
                            <div className="flex items-center gap-2">
                              <Dropdown placement="bottom-end">
                                <DropdownTrigger>
                                  <Button
                                    variant="flat"
                                    size="sm"
                                    color="primary"
                                    isLoading={isRegeneratingSteps}
                                    isDisabled={isRegeneratingSteps}
                                    endContent={
                                      !isRegeneratingSteps && (
                                        <ArrowDown01Icon className="h-3 w-3" />
                                      )
                                    }
                                    startContent={
                                      !isRegeneratingSteps && (
                                        <RedoIcon className="h-4 w-4" />
                                      )
                                    }
                                  >
                                    {isRegeneratingSteps
                                      ? "Regenerating..."
                                      : "Regenerate"}
                                  </Button>
                                </DropdownTrigger>
                                <DropdownMenu
                                  aria-label="Regeneration reasons"
                                  onAction={(key) =>
                                    handleRegenerateWithReason(key as string)
                                  }
                                  disabledKeys={
                                    isRegeneratingSteps ? ["all"] : []
                                  }
                                >
                                  {regenerationReasons.map((reason) => (
                                    <DropdownItem
                                      key={reason.key}
                                      textValue={reason.label}
                                      description={reason.description}
                                    >
                                      {reason.label}
                                    </DropdownItem>
                                  ))}
                                </DropdownMenu>
                              </Dropdown>
                            </div>
                          </div>
                          <div className="min-h-0 flex-1 overflow-y-auto">
                            <Skeleton
                              className="h-full rounded-2xl"
                              isLoaded={
                                !(isRegeneratingSteps || isGeneratingSteps)
                              }
                            >
                              <WorkflowSteps
                                steps={currentWorkflow.steps || []}
                              />
                            </Skeleton>
                          </div>
                        </>
                      ) : (
                        // Show empty state with generate button (when no steps in either source)
                        <div className="space-y-4">
                          <div className="flex items-center justify-between">
                            <div>
                              <h4 className="font-medium text-zinc-200">
                                Workflow Steps
                              </h4>
                              <p className="text-xs text-zinc-500">
                                No steps generated yet
                              </p>
                            </div>
                            <div className="flex items-center gap-2">
                              <Button
                                variant="flat"
                                size="sm"
                                color="primary"
                                isLoading={isRegeneratingSteps}
                                isDisabled={isRegeneratingSteps}
                                startContent={<RedoIcon className="h-4 w-4" />}
                                onPress={handleInitialGeneration}
                              >
                                Generate Steps
                              </Button>
                            </div>
                          </div>
                          <div className="flex flex-col items-center justify-center py-8 text-center">
                            <div className="mb-4 rounded-full bg-zinc-800/50 p-3">
                              <RedoIcon className="h-6 w-6 text-zinc-500" />
                            </div>
                            <p className="text-sm text-zinc-400">
                              Click "Generate Steps" to create your first
                              workflow plan
                            </p>
                          </div>
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}
            </div>
          ) : creationPhase === "error" ? (
            <div className="flex flex-col items-center justify-center space-y-4 py-8">
              <AlertCircleIcon className="h-12 w-12 text-danger" />
              <div className="text-center">
                <h3 className="text-lg font-medium text-danger">
                  {mode === "create" ? "Creation" : "Update"} Failed
                </h3>
                <p className="text-sm text-zinc-400">
                  {creationError ||
                    `Something went wrong while ${mode === "create" ? "creating" : "updating"} the workflow`}
                </p>
              </div>
              <div className="flex gap-3">
                <Button variant="flat" onPress={handleClose}>
                  Cancel
                </Button>
                <Button
                  color="primary"
                  onPress={() => setCreationPhase("form")}
                >
                  Try Again
                </Button>
              </div>
            </div>
          ) : creationPhase === "creating" ? (
            <div className="flex flex-col items-center justify-center space-y-4 py-8">
              <CustomSpinner variant="logo" />
              <div className="text-center">
                <h3 className="text-lg font-medium">Creating Workflow</h3>
                <p className="text-sm text-zinc-400">
                  Setting up your workflow and generating steps...
                </p>
              </div>
            </div>
          ) : creationPhase === "success" ? (
            <div className="flex flex-col space-y-6 py-6">
              <div className="flex flex-col items-center justify-center space-y-4">
                <CheckmarkCircle02Icon className="h-16 w-16 text-success" />
                <div className="text-center">
                  <h3 className="text-lg font-medium text-success">
                    Workflow {mode === "create" ? "Created" : "Updated"}!
                  </h3>
                  <p className="text-sm text-zinc-400">
                    "{currentWorkflow?.title || "Untitled Workflow"}" is ready
                    to use
                  </p>
                  {currentWorkflow && (
                    <p className="mt-2 text-xs text-zinc-500">
                      {currentWorkflow?.steps?.length || 0} steps generated
                    </p>
                  )}
                </div>
                {/* Close button */}
                <Button
                  color="primary"
                  variant="flat"
                  onPress={handleClose}
                  className="mt-4"
                >
                  Close
                </Button>
              </div>

              {/* Generated Steps Preview */}
              {currentWorkflow?.steps && currentWorkflow.steps.length > 0 && (
                <div className="space-y-3">
                  <h4 className="text-sm font-medium text-zinc-300">
                    Generated Steps:
                  </h4>
                  <div className="max-h-48 overflow-y-auto">
                    <WorkflowSteps steps={currentWorkflow.steps} />
                  </div>
                </div>
              )}
            </div>
          ) : null}
        </ModalBody>
      </ModalContent>
    </Modal>
  );
}

"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { toast } from "@/lib/toast";
import { useAppendToInput } from "@/stores/composerStore";
import type {
  CommunityWorkflow,
  PublicWorkflowStep,
  TriggerConfig,
  Workflow,
} from "@/types/features/workflowTypes";
import { useWorkflowCreation } from "../../hooks/useWorkflowCreation";

interface UseWorkflowCardActionsParams {
  /** Card payload — any subset of these drives the default/create flows */
  workflow?: Workflow;
  communityWorkflow?: CommunityWorkflow;
  title: string;
  displayDescription: string;
  description?: string;
  steps: PublicWorkflowStep[];
  slug?: string;
  prompt?: string;
  variant: "user" | "community" | "explore" | "suggestion";
  sourceTriggerConfig?: TriggerConfig;
  systemWorkflowKey?: string | null;
  resolvedAction: "run" | "create" | "insert-prompt" | "navigate" | "none";
  onCardClick?: () => void;
  onActionComplete?: () => void;
}

/**
 * All card-level actions (run / create / insert prompt / navigate) plus the
 * loading flag they share. Extracted from UnifiedWorkflowCard so the card
 * component stays focused on rendering.
 */
export function useWorkflowCardActions({
  workflow,
  communityWorkflow,
  title,
  displayDescription,
  description,
  steps,
  slug,
  prompt,
  variant,
  sourceTriggerConfig,
  systemWorkflowKey,
  resolvedAction,
  onCardClick,
  onActionComplete,
}: UseWorkflowCardActionsParams) {
  const [isLoading, setIsLoading] = useState(false);
  const router = useRouter();

  // Auth check
  const { isAuthenticated, openLoginModal } = useAuth();

  const { selectWorkflow } = useWorkflowSelection();
  const { createWorkflow } = useWorkflowCreation();
  const appendToInput = useAppendToInput();

  const handleRunWorkflow = async () => {
    if (!workflow || isLoading) return;
    setIsLoading(true);
    try {
      trackEvent(ANALYTICS_EVENTS.WORKFLOWS_EXECUTED, {
        workflow_id: workflow.id,
        step_count: workflow.steps?.length || 0,
        trigger_type: workflow.trigger_config.type,
      });
      selectWorkflow(workflow, { autoSend: true });
      onActionComplete?.();
    } catch (error) {
      console.error("Error running workflow:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleCreateWorkflow = async () => {
    if (isLoading) return;

    // Check authentication first - open login modal if not authenticated
    if (!isAuthenticated) {
      openLoginModal();
      return;
    }

    setIsLoading(true);
    const toastId = toast.loading("Creating workflow...");

    try {
      // Convert PublicWorkflowStep to WorkflowStepData format if steps exist
      const formattedSteps = steps?.map((step, index) => ({
        id: step.id || `step_${index}`,
        title: step.title,
        description: step.description,
        category: step.category,
      }));

      const workflowRequest = {
        title,
        description: communityWorkflow?.description || description || undefined,
        prompt: communityWorkflow?.prompt || displayDescription || title,
        // Reproduce the trigger the card advertises; manual only as a fallback.
        trigger_config: sourceTriggerConfig ?? {
          type: "manual" as const,
          enabled: true,
        },
        system_workflow_key: systemWorkflowKey,
        // Pass formatted steps if available to avoid regeneration
        ...(formattedSteps &&
          formattedSteps.length > 0 && {
            steps: formattedSteps,
          }),
        // Only generate if no steps exist
        generate_immediately: !formattedSteps || formattedSteps.length === 0,
      };

      const result = await createWorkflow(workflowRequest);

      if (result.success && result.workflow) {
        toast.success("Workflow created successfully!", { id: toastId });
        trackEvent(ANALYTICS_EVENTS.WORKFLOWS_CREATED, {
          workflow_id: result.workflow.id,
          step_count: result.workflow.steps?.length || 0,
          trigger_type: "manual",
          has_schedule: false,
        });
        selectWorkflow(result.workflow, { autoSend: variant === "suggestion" });
        onActionComplete?.();
      }
    } catch (error) {
      toast.error("Error creating workflow", { id: toastId });
      console.error("Workflow creation error:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleInsertPrompt = () => {
    if (prompt) {
      // `title` is user-authored free text — intentionally not sent.
      trackEvent(ANALYTICS_EVENTS.USE_CASES_PROMPT_INSERTED);
      appendToInput(prompt);
      router.push("/c");
      onActionComplete?.();
    }
  };

  const handleNavigate = () => {
    const targetSlug = slug || communityWorkflow?.slug || workflow?.slug;
    if (targetSlug) {
      trackEvent(ANALYTICS_EVENTS.WORKFLOW_CARD_NAVIGATE, {
        slug: targetSlug,
        variant,
      });
      router.push(`/use-cases/${targetSlug}`);
    }
  };

  const handlePrimaryAction = async () => {
    switch (resolvedAction) {
      case "run":
        await handleRunWorkflow();
        break;
      case "create":
        await handleCreateWorkflow();
        break;
      case "insert-prompt":
        handleInsertPrompt();
        break;
      case "navigate":
        handleNavigate();
        break;
      default:
        break;
    }
  };

  const handleCardClick = () => {
    if (onCardClick) {
      onCardClick();
      return;
    }

    // Default card click behavior
    if (variant === "suggestion") {
      handleCreateWorkflow();
    } else if (variant === "user" && workflow) {
      handleRunWorkflow();
    } else {
      handleNavigate();
    }
  };

  return { isLoading, handlePrimaryAction, handleCardClick };
}

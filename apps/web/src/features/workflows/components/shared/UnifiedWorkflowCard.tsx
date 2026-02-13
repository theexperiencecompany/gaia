"use client";

import { Button } from "@heroui/button";
import { Tooltip } from "@heroui/tooltip";
import { PlayIcon, ZapIcon } from "@icons";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { useAppendToInput } from "@/stores/composerStore";
import type {
  CommunityWorkflow,
  PublicWorkflowStep,
  Workflow,
} from "@/types/features/workflowTypes";
import { formatRunCount } from "@/utils/formatters";
import { useWorkflowCreation } from "../../hooks/useWorkflowCreation";
import { getTriggerDisplayInfo } from "../../triggers";
import {
  ActivationStatus,
  CreatorAvatar,
  getNextRunDisplay,
  TriggerDisplay,
} from "./WorkflowCardComponents";
import WorkflowIcons from "./WorkflowIcons";

type WorkflowVariant = "user" | "community" | "explore" | "suggestion";
type ActionType = "run" | "create" | "insert-prompt" | "navigate" | "none";

interface UnifiedWorkflowCardProps {
  // Core data - accepts either full Workflow or simplified data
  workflow?: Workflow;
  communityWorkflow?: CommunityWorkflow;
  // Simplified props for direct use (alternative to workflow objects)
  title?: string;
  description?: string;
  steps?: PublicWorkflowStep[];
  totalExecutions?: number;
  slug?: string;
  prompt?: string;
  actionType?: "prompt" | "workflow";

  // Display configuration
  variant?: WorkflowVariant;
  showTrigger?: boolean;
  showExecutions?: boolean;
  showActivationStatus?: boolean;
  showCreator?: boolean;
  useBlurEffect?: boolean;
  showDescriptionAsTooltip?: boolean;

  // Action configuration
  primaryAction?: ActionType;
  onCardClick?: () => void;
  onActionComplete?: () => void;

  // Button customization
  actionButtonLabel?: string;
}

export default function UnifiedWorkflowCard({
  workflow,
  communityWorkflow,
  title: propTitle,
  description: propDescription,
  steps: propSteps,
  totalExecutions: propTotalExecutions,
  slug,
  prompt,
  actionType: propActionType,
  variant = "explore",
  showTrigger,
  showExecutions = true,
  showActivationStatus = false,
  showCreator,
  useBlurEffect = false,
  showDescriptionAsTooltip = false,
  primaryAction,
  onCardClick,
  onActionComplete,
  actionButtonLabel,
}: UnifiedWorkflowCardProps) {
  const [isLoading, setIsLoading] = useState(false);
  const router = useRouter();

  // Auth check
  const { isAuthenticated, openLoginModal } = useAuth();

  const { selectWorkflow } = useWorkflowSelection();
  const { createWorkflow } = useWorkflowCreation();
  const { integrations } = useIntegrations();
  const appendToInput = useAppendToInput();

  // Normalize data from different sources
  const title = propTitle || workflow?.title || communityWorkflow?.title || "";
  const description =
    propDescription ||
    workflow?.description ||
    communityWorkflow?.description ||
    "";
  const steps = propSteps || workflow?.steps || communityWorkflow?.steps || [];
  const totalExecutions =
    propTotalExecutions ??
    workflow?.total_executions ??
    communityWorkflow?.total_executions ??
    0;
  const creator = communityWorkflow?.creator || workflow?.creator;

  // Determine display settings based on variant
  const shouldShowTrigger = showTrigger ?? (variant === "user" && !!workflow);
  const shouldShowCreator =
    showCreator ?? (variant === "community" && !!creator);
  const shouldShowActivation =
    showActivationStatus ?? (variant === "user" && !!workflow);

  // Determine primary action based on variant and props
  const resolvedAction = primaryAction ?? getDefaultAction(variant);

  // Get trigger info for user workflows
  const triggerDisplay = workflow
    ? getTriggerDisplayInfo(workflow, integrations)
    : null;
  const nextRunText = workflow ? getNextRunDisplay(workflow) : null;

  // Action handlers
  const handleRunWorkflow = async () => {
    if (!workflow || isLoading) return;
    setIsLoading(true);
    try {
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
        description,
        trigger_config: {
          type: "manual" as const,
          enabled: true,
        },
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
      trackEvent(ANALYTICS_EVENTS.USE_CASES_PROMPT_INSERTED, { title });
      appendToInput(prompt);
      router.push("/c");
      onActionComplete?.();
    }
  };

  const handleNavigate = () => {
    const targetSlug = slug || communityWorkflow?.id || workflow?.id;
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

  // Get button configuration
  const buttonConfig = getButtonConfig(
    resolvedAction,
    actionButtonLabel,
    propActionType,
  );

  // Render tool icons using the shared component
  const renderToolIcons = () => (
    <WorkflowIcons steps={steps} iconSize={25} maxIcons={3} />
  );

  const isClickable = onCardClick || resolvedAction !== "none";

  const cardContent = (
    <div
      className={`group relative z-1 flex h-full min-h-fit w-full flex-col gap-2 rounded-3xl outline-1 ${
        useBlurEffect
          ? "bg-zinc-800/40 outline-zinc-800/50 backdrop-blur-lg"
          : "bg-zinc-800 outline-zinc-800/70"
      } p-4 transition-all select-none ${
        isClickable ? "cursor-pointer hover:bg-zinc-700/50" : ""
      }`}
      onClick={handleCardClick}
    >
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">{renderToolIcons()}</div>
        {shouldShowActivation && workflow && (
          <ActivationStatus activated={workflow.activated} />
        )}
      </div>

      <div>
        <h3 className="line-clamp-2 text-lg font-medium">{title}</h3>
        {!showDescriptionAsTooltip && (
          <div className="mt-1 line-clamp-2 min-h-8 flex-1 text-xs text-zinc-500">
            {description}
          </div>
        )}
      </div>

      <div className="mt-auto">
        <div className="mt-1 flex items-center justify-between gap-2">
          <div className="space-y-1">
            {shouldShowTrigger && triggerDisplay && (
              <TriggerDisplay
                triggerType={workflow?.trigger_config.type || "manual"}
                triggerLabel={triggerDisplay.label
                  .split(" ")
                  .map(
                    (word: string) =>
                      word.charAt(0).toUpperCase() +
                      word.slice(1).toLowerCase(),
                  )
                  .join(" ")}
                integrationId={triggerDisplay.integrationId}
                nextRunText={nextRunText || undefined}
              />
            )}

            {showExecutions && totalExecutions > 0 && (
              <div className="flex items-center gap-1 text-xs text-zinc-500">
                <PlayIcon
                  width={15}
                  height={15}
                  className="w-4 text-zinc-500"
                />
                <span className="text-nowrap">
                  {formatRunCount(totalExecutions)}
                </span>
              </div>
            )}
          </div>

          <div className="flex items-center gap-3">
            {shouldShowCreator && creator && (
              <CreatorAvatar creator={creator} />
            )}

            {resolvedAction !== "none" && (
              <WorkflowActionButton
                label={buttonConfig.label}
                isLoading={isLoading}
                onPress={handlePrimaryAction}
                variant={buttonConfig.variant}
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );

  return showDescriptionAsTooltip ? (
    <Tooltip
      content={description}
      placement="top"
      className="max-w-xs"
      showArrow
      classNames={{
        content: "bg-zinc-800 p-4 rounded-3xl",
      }}
      delay={200}
      closeDelay={0}
    >
      {cardContent}
    </Tooltip>
  ) : (
    cardContent
  );
}

// Helper function to determine default action based on variant
function getDefaultAction(variant: WorkflowVariant): ActionType {
  switch (variant) {
    case "user":
      return "run";
    case "community":
    case "explore":
      return "create";
    case "suggestion":
      return "create";
    default:
      return "none";
  }
}

// Helper function to get button configuration
function getButtonConfig(
  action: ActionType,
  customLabel?: string,
  propActionType?: "prompt" | "workflow",
): { label: string; variant: "primary" | "flat" } {
  if (customLabel) {
    return { label: customLabel, variant: "primary" };
  }

  // Handle prompt vs workflow action type
  if (propActionType === "prompt") {
    return { label: "Insert Prompt", variant: "primary" };
  }

  switch (action) {
    case "run":
      return { label: "Run", variant: "flat" };
    case "create":
      return { label: "Create", variant: "primary" };
    case "insert-prompt":
      return { label: "Insert Prompt", variant: "primary" };
    case "navigate":
      return { label: "View", variant: "flat" };
    default:
      return { label: "Try", variant: "primary" };
  }
}

// Unified action button component
interface WorkflowActionButtonProps {
  label: string;
  isLoading: boolean;
  onPress: (e: React.MouseEvent) => void;
  variant?: "primary" | "flat";
  size?: "sm" | "md";
}

export function WorkflowActionButton({
  label,
  isLoading,
  onPress,
  variant = "primary",
  size = "sm",
}: WorkflowActionButtonProps) {
  const buttonVariant = variant === "flat" ? "flat" : "solid";
  const showIcon = label !== "Run Workflow";

  return (
    <Button
      color="primary"
      size={size}
      variant={buttonVariant}
      className={`font-medium rounded-xl ${variant === "flat" ? "text-primary" : ""}`}
      isLoading={isLoading}
      onPress={(e) => onPress(e as unknown as React.MouseEvent)}
      endContent={showIcon ? <ZapIcon width={16} height={16} /> : undefined}
    >
      {label}
    </Button>
  );
}

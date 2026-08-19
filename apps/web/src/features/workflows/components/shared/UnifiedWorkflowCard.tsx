"use client";

import { Button } from "@heroui/button";
import { Tooltip } from "@heroui/tooltip";
import { PlayIcon } from "@icons";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { Link } from "@/i18n/navigation";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { toast } from "@/lib/toast";
import { useAppendToInput } from "@/stores/composerStore";
import type {
  CommunityWorkflow,
  IntegrationRef,
  PublicWorkflowStep,
  TriggerConfig,
  Workflow,
} from "@/types/features/workflowTypes";
import type { ContentCreator } from "@/types/shared/contentTypes";
import { formatRunCount } from "@/utils/formatters";
import { useWorkflowCreation } from "../../hooks/useWorkflowCreation";
import { getTriggerDisplayInfo } from "../../triggers/utils";
import { isSystemCreator } from "../../utils/creator";
import {
  ActivationStatus,
  CreatorAvatar,
  getNextRunDisplay,
  MissingIntegrationsWarning,
  SystemWorkflowChip,
  TriggerDisplay,
} from "./WorkflowCardComponents";
import WorkflowIcons from "./WorkflowIcons";

type WorkflowVariant = "user" | "community" | "explore" | "suggestion";
type ActionType = "run" | "create" | "insert-prompt" | "navigate" | "none";

interface UnifiedWorkflowCardProps {
  workflow?: Workflow;
  communityWorkflow?: CommunityWorkflow;
  title?: string;
  description?: string;
  steps?: PublicWorkflowStep[];
  icon?: string | null;
  iconColor?: string | null;
  systemWorkflowKey?: string | null;
  triggerConfig?: TriggerConfig;
  creator?: ContentCreator;
  totalExecutions?: number;
  slug?: string;
  prompt?: string;
  actionType?: "prompt" | "workflow";
  variant?: WorkflowVariant;
  showTrigger?: boolean;
  showExecutions?: boolean;
  showActivationStatus?: boolean;
  showCreator?: boolean;
  useBlurEffect?: boolean;
  showDescriptionAsTooltip?: boolean;
  primaryAction?: ActionType;
  onCardClick?: () => void;
  onActionComplete?: () => void;
  href?: string;
  actionButtonLabel?: string;
  missingIntegrations?: IntegrationRef[];
}

function useWorkflowCardActions({
  workflow,
  communityWorkflow,
  title,
  displayDescription,
  steps,
  systemWorkflowKey,
  sourceTriggerConfig,
  prompt,
  slug,
  variant,
  onActionComplete,
  resolvedAction,
  isLoading,
  setIsLoading,
}: {
  workflow?: Workflow;
  communityWorkflow?: CommunityWorkflow;
  title: string;
  displayDescription: string;
  steps: PublicWorkflowStep[];
  systemWorkflowKey?: string;
  sourceTriggerConfig?: TriggerConfig;
  prompt?: string;
  slug?: string;
  variant: WorkflowVariant;
  onActionComplete?: () => void;
  resolvedAction: ActionType;
  isLoading: boolean;
  setIsLoading: (loading: boolean) => void;
}) {
  const router = useRouter();
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
    if (!isAuthenticated) {
      openLoginModal();
      return;
    }
    setIsLoading(true);
    const toastId = toast.loading("Creating workflow...");
    try {
      const formattedSteps = steps?.map((step, index) => ({
        id: step.id || `step_${index}`,
        title: step.title,
        description: step.description,
        category: step.category,
      }));
      const workflowRequest = {
        title,
        description:
          communityWorkflow?.description || displayDescription || undefined,
        prompt: communityWorkflow?.prompt || displayDescription || title,
        trigger_config: sourceTriggerConfig ?? {
          type: "manual" as const,
          enabled: true,
        },
        system_workflow_key: systemWorkflowKey,
        ...(formattedSteps &&
          formattedSteps.length > 0 && {
            steps: formattedSteps,
          }),
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
  const handleCardClick = (onCardClick?: () => void) => {
    if (onCardClick) {
      onCardClick();
      return;
    }
    if (variant === "suggestion") {
      handleCreateWorkflow();
    } else if (variant === "user" && workflow) {
      handleRunWorkflow();
    } else {
      handleNavigate();
    }
  };
  return {
    handleRunWorkflow,
    handleCreateWorkflow,
    handleInsertPrompt,
    handleNavigate,
    handlePrimaryAction,
    handleCardClick,
  };
}

interface WorkflowCardHeaderProps {
  steps: PublicWorkflowStep[];
  customIcon?: string | null;
  customIconColor?: string | null;
  resolvedMissingIntegrations?: IntegrationRef[];
  shouldShowActivation: boolean;
  workflow?: Workflow;
}

function WorkflowCardHeader({
  steps,
  customIcon,
  customIconColor,
  resolvedMissingIntegrations,
  shouldShowActivation,
  workflow,
}: WorkflowCardHeaderProps) {
  return (
    <div className="flex items-start justify-between">
      <div className="flex items-center gap-2">
        <WorkflowIcons
          steps={steps}
          icon={customIcon}
          iconColor={customIconColor}
          iconSize={25}
          maxIcons={3}
        />
      </div>
      <div className="flex items-center gap-2">
        {resolvedMissingIntegrations?.length ? (
          <MissingIntegrationsWarning
            missingIntegrations={resolvedMissingIntegrations}
          />
        ) : (
          shouldShowActivation &&
          workflow && <ActivationStatus activated={workflow.activated} />
        )}
      </div>
    </div>
  );
}

interface WorkflowCardTitleProps {
  title: string;
  displayDescription: string;
  showDescriptionAsTooltip: boolean;
}

function WorkflowCardTitle({
  title,
  displayDescription,
  showDescriptionAsTooltip,
}: WorkflowCardTitleProps) {
  return (
    <div>
      <div className="flex items-center gap-2">
        <h3 className="line-clamp-2 text-lg font-medium">{title}</h3>
      </div>
      {!showDescriptionAsTooltip && (
        <div className="mt-1 line-clamp-2 min-h-8 flex-1 text-xs text-zinc-500">
          {displayDescription}
        </div>
      )}
    </div>
  );
}

interface WorkflowCardMetaProps {
  shouldShowCreator: boolean;
  creator?: ContentCreator;
  shouldShowTrigger: boolean;
  triggerDisplay: ReturnType<typeof getTriggerDisplayInfo> | null;
  triggerType?: string;
  nextRunText: string | null;
  showExecutions: boolean;
  totalExecutions: number;
}

function WorkflowCardMeta({
  shouldShowCreator,
  creator,
  shouldShowTrigger,
  triggerDisplay,
  triggerType,
  nextRunText,
  showExecutions,
  totalExecutions,
}: WorkflowCardMetaProps) {
  return (
    <div className="min-w-0 space-y-1">
      {shouldShowCreator && creator && (
        <CreatorAvatar creator={creator} showName />
      )}
      {shouldShowTrigger && triggerDisplay && (
        <TriggerDisplay
          triggerType={triggerType || "manual"}
          triggerLabel={triggerDisplay.label
            .split(" ")
            .map(
              (word: string) =>
                word.charAt(0).toUpperCase() + word.slice(1).toLowerCase(),
            )
            .join(" ")}
          integrationId={triggerDisplay.integrationId}
          nextRunText={nextRunText || undefined}
        />
      )}
      {showExecutions && totalExecutions > 0 && (
        <div className="flex items-center gap-1 text-xs text-zinc-500">
          <PlayIcon width={15} height={15} className="w-4 text-zinc-500" />
          <span className="text-nowrap">{formatRunCount(totalExecutions)}</span>
        </div>
      )}
    </div>
  );
}

interface WorkflowCardFooterProps {
  workflow?: Workflow;
  resolvedAction: ActionType;
  buttonConfig: { label: string; variant: "primary" | "flat" };
  isLoading: boolean;
  onPrimaryAction: () => void;
  meta: React.ReactNode;
}

function WorkflowCardFooter({
  workflow,
  resolvedAction,
  buttonConfig,
  isLoading,
  onPrimaryAction,
  meta,
}: WorkflowCardFooterProps) {
  return (
    <div className="mt-auto">
      <div className="mt-1 flex items-center justify-between gap-2">
        {meta}
        <div className="flex items-center gap-3">
          {workflow?.is_system_workflow && <SystemWorkflowChip />}
          {resolvedAction !== "none" && (
            <span className="relative z-[2]">
              <WorkflowActionButton
                label={buttonConfig.label}
                isLoading={isLoading}
                onPress={(e: React.MouseEvent) => {
                  e.stopPropagation();
                  onPrimaryAction();
                }}
                variant={buttonConfig.variant}
              />
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

export default function UnifiedWorkflowCard(props: UnifiedWorkflowCardProps) {
  const {
    workflow,
    communityWorkflow,
    slug,
    prompt,
    actionType: propActionType,
    variant = "explore",
    showExecutions = true,
    useBlurEffect = false,
    showDescriptionAsTooltip = false,
    onCardClick,
    onActionComplete,
    actionButtonLabel,
    href,
  } = props;
  const [isLoading, setIsLoading] = useState(false);
  const { integrations } = useIntegrations();
  const {
    title,
    displayDescription,
    steps,
    customIcon,
    customIconColor,
    systemWorkflowKey,
    sourceTriggerConfig,
    totalExecutions,
    creator,
    shouldShowTrigger,
    shouldShowCreator,
    shouldShowActivation,
    resolvedAction,
    resolvedMissingIntegrations,
    isClickable,
  } = deriveWorkflowCardConfig(props);
  const triggerDisplay = workflow
    ? getTriggerDisplayInfo(workflow, integrations)
    : null;
  const nextRunText = workflow ? getNextRunDisplay(workflow) : null;
  const { handlePrimaryAction, handleCardClick } = useWorkflowCardActions({
    workflow,
    communityWorkflow,
    title,
    displayDescription,
    steps,
    systemWorkflowKey,
    sourceTriggerConfig,
    prompt,
    slug,
    variant,
    onActionComplete,
    resolvedAction,
    isLoading,
    setIsLoading,
  });
  const buttonConfig = getButtonConfig(
    resolvedAction,
    actionButtonLabel,
    propActionType,
  );
  const onCardPress = href ? undefined : () => handleCardClick(onCardClick);
  const header = (
    <WorkflowCardHeader
      steps={steps}
      customIcon={customIcon}
      customIconColor={customIconColor}
      resolvedMissingIntegrations={resolvedMissingIntegrations}
      shouldShowActivation={shouldShowActivation}
      workflow={workflow}
    />
  );
  const titleSection = (
    <WorkflowCardTitle
      title={title}
      displayDescription={displayDescription}
      showDescriptionAsTooltip={showDescriptionAsTooltip}
    />
  );
  const meta = (
    <WorkflowCardMeta
      shouldShowCreator={shouldShowCreator}
      creator={creator}
      shouldShowTrigger={shouldShowTrigger}
      triggerDisplay={triggerDisplay}
      triggerType={workflow?.trigger_config.type}
      nextRunText={nextRunText}
      showExecutions={showExecutions}
      totalExecutions={totalExecutions}
    />
  );
  const cardContent = (
    <div
      className={`group relative z-1 flex h-full min-h-fit w-full flex-col gap-2 rounded-3xl outline-1 ${useBlurEffect ? "bg-zinc-800/40 outline-zinc-800/50 backdrop-blur-lg" : "bg-zinc-800 outline-zinc-800/70"} p-4 transition-all select-none ${isClickable ? "cursor-pointer hover:bg-zinc-700/50" : ""}`}
      onClick={onCardPress}
    >
      {href && (
        <Link
          href={href}
          aria-label={title}
          className="absolute inset-0 z-[1] rounded-3xl"
        />
      )}
      {header}
      {titleSection}
      <WorkflowCardFooter
        workflow={workflow}
        resolvedAction={resolvedAction}
        buttonConfig={buttonConfig}
        isLoading={isLoading}
        onPrimaryAction={handlePrimaryAction}
        meta={meta}
      />
    </div>
  );
  return showDescriptionAsTooltip ? (
    <Tooltip
      content={workflow?.prompt || displayDescription}
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

function deriveWorkflowCardConfig(props: UnifiedWorkflowCardProps) {
  const {
    workflow,
    communityWorkflow,
    title: propTitle,
    description: propDescription,
    steps: propSteps,
    icon: propIcon,
    iconColor: propIconColor,
    systemWorkflowKey: propSystemWorkflowKey,
    triggerConfig: propTriggerConfig,
    creator: propCreator,
    totalExecutions: propTotalExecutions,
    variant = "explore",
    showTrigger,
    showActivationStatus = false,
    showCreator,
    primaryAction,
    onCardClick,
    href,
    missingIntegrations: propMissingIntegrations,
  } = props;
  const title = propTitle || workflow?.title || communityWorkflow?.title || "";
  const displayDescription =
    propDescription ||
    workflow?.description ||
    communityWorkflow?.description ||
    "";
  const steps = propSteps || workflow?.steps || communityWorkflow?.steps || [];
  const customIcon = propIcon ?? workflow?.icon ?? communityWorkflow?.icon;
  const customIconColor =
    propIconColor ?? workflow?.icon_color ?? communityWorkflow?.icon_color;
  const totalExecutions =
    propTotalExecutions ??
    workflow?.total_executions ??
    communityWorkflow?.total_executions ??
    0;
  const creator =
    propCreator || communityWorkflow?.creator || workflow?.creator;
  const shouldShowTrigger = showTrigger ?? (variant === "user" && !!workflow);
  const shouldShowCreator =
    (showCreator ?? variant === "community") &&
    !!creator &&
    !isSystemCreator(creator);
  const shouldShowActivation =
    showActivationStatus ?? (variant === "user" && !!workflow);
  const resolvedAction = primaryAction ?? getDefaultAction(variant);
  const resolvedMissingIntegrations =
    propMissingIntegrations ?? workflow?.missing_integrations;
  const isClickable = !!href || onCardClick || resolvedAction !== "none";
  const systemWorkflowKey =
    propSystemWorkflowKey ??
    communityWorkflow?.system_workflow_key ??
    undefined;
  const sourceTriggerConfig =
    propTriggerConfig ?? communityWorkflow?.trigger_config;
  return {
    title,
    displayDescription,
    steps,
    customIcon,
    customIconColor,
    systemWorkflowKey,
    sourceTriggerConfig,
    totalExecutions,
    creator,
    shouldShowTrigger,
    shouldShowCreator,
    shouldShowActivation,
    resolvedAction,
    resolvedMissingIntegrations,
    isClickable,
  };
}

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

function getButtonConfig(
  action: ActionType,
  customLabel?: string,
  propActionType?: "prompt" | "workflow",
): { label: string; variant: "primary" | "flat" } {
  if (customLabel) {
    return { label: customLabel, variant: "primary" };
  }
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

interface WorkflowActionButtonProps {
  label: string;
  isLoading: boolean;
  onPress: (e: React.MouseEvent) => void;
  variant?: "primary" | "flat";
  size?: "sm" | "md";
}

function WorkflowActionButton({
  label,
  isLoading,
  onPress,
  variant = "primary",
  size = "sm",
}: WorkflowActionButtonProps) {
  const buttonVariant = variant === "flat" ? "flat" : "solid";
  return (
    <Button
      color="primary"
      size={size}
      variant={buttonVariant}
      className={`font-medium rounded-xl ${variant === "flat" ? "text-primary" : ""}`}
      isLoading={isLoading}
      onPress={(e) => onPress(e as unknown as React.MouseEvent)}
    >
      {label}
    </Button>
  );
}

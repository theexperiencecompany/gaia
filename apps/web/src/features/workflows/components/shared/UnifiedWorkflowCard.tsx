"use client";

import { Tooltip } from "@heroui/react";
import { PlayIcon } from "@icons";
import type { ImageProps } from "next/image";
import { SiteLink } from "@/components/seo/SiteLink";
import { overlayVariants } from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import type {
  CommunityWorkflow,
  IntegrationRef,
  PublicWorkflowStep,
  UseCase,
  Workflow,
} from "@/types/features/workflowTypes";
import { formatRunCount } from "@/utils/formatters";
import { WORKFLOW_CARD_ICON_SIZE } from "../../constants/workflowIconStyle";
import { getTriggerDisplayInfo } from "../../triggers/utils";
import { isSystemCreator } from "../../utils/creator";
import { useWorkflowCardActions } from "./useWorkflowCardActions";
import {
  ActivationStatus,
  CreatorAvatar,
  MissingIntegrationsWarning,
  SystemWorkflowChip,
  TriggerDisplay,
} from "./WorkflowCardComponents";
import WorkflowIcons from "./WorkflowIcons";
import { getNextRunDisplay } from "./workflowCardHelpers";

export type WorkflowVariant = "user" | "community" | "explore" | "suggestion";
type WorkflowCardAction =
  | "run"
  | "create"
  | "insert-prompt"
  | "navigate"
  | "none";

interface UnifiedWorkflowCardProps {
  // Core data: one of a user workflow, a community workflow or a use case
  workflow?: Workflow;
  communityWorkflow?: CommunityWorkflow;
  useCase?: UseCase;
  // Display-only fields for a selected workflow that has none of the above
  title?: string;
  description?: string;
  steps?: PublicWorkflowStep[];

  // Display configuration
  variant?: WorkflowVariant;
  showTrigger?: boolean;
  showExecutions?: boolean;
  showActivationStatus?: boolean;
  showCreator?: boolean;
  useBlurEffect?: boolean;
  showDescriptionAsTooltip?: boolean;
  /** Eager for a card in the first viewport: its icons and avatar load with the page. */
  imageLoading?: ImageProps["loading"];

  // Action configuration
  primaryAction?: WorkflowCardAction;
  onCardClick?: () => void;
  onActionComplete?: () => void;
  /**
   * When set, the whole card becomes a real crawlable link to this URL (no
   * client-side router.push). The action button stays clickable above it.
   */
  href?: string;

  // Button customization
  actionButtonLabel?: string;

  // Explicit missing integrations override (for cards that don't pass a full workflow object)
  missingIntegrations?: IntegrationRef[];
}

export default function UnifiedWorkflowCard(props: UnifiedWorkflowCardProps) {
  const {
    workflow,
    communityWorkflow,
    useCase,
    description: propDescription,
    variant = "explore",
    showExecutions = true,
    useBlurEffect = false,
    showDescriptionAsTooltip = false,
    imageLoading,
    onCardClick,
    onActionComplete,
    actionButtonLabel,
    href,
  } = props;

  const { integrations } = useIntegrations();

  // Normalize data + display settings from the various supported prop sources.
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

  // Get trigger info for user workflows
  const triggerDisplay = workflow
    ? getTriggerDisplayInfo(workflow, integrations)
    : null;
  const nextRunText = workflow ? getNextRunDisplay(workflow) : null;

  // All card-level actions (run / create / insert prompt / navigate) plus the
  // loading flag they share, extracted to keep this card focused on rendering.
  const { isLoading, handlePrimaryAction, handleCardClick } =
    useWorkflowCardActions({
      workflow,
      communityWorkflow,
      title,
      displayDescription,
      description: propDescription ?? useCase?.description,
      steps,
      slug: useCase?.slug,
      prompt: useCase?.prompt,
      variant,
      sourceTriggerConfig,
      systemWorkflowKey,
      resolvedAction,
      onCardClick,
      onActionComplete,
    });

  // Get button configuration
  const buttonConfig = getButtonConfig(
    resolvedAction,
    actionButtonLabel,
    useCase?.action_type,
  );

  // Render tool icons using the shared component
  const renderToolIcons = () => (
    <WorkflowIcons
      steps={steps}
      icon={customIcon}
      iconColor={customIconColor}
      iconSize={WORKFLOW_CARD_ICON_SIZE}
      maxIcons={3}
      loading={imageLoading}
    />
  );

  const cardContent = (
    <div
      className={`group relative z-1 flex h-full min-h-fit w-full flex-col gap-2 rounded-3xl outline-1 ${useBlurEffect ? "bg-zinc-800/40 outline-zinc-800/50 backdrop-blur-lg" : "bg-zinc-800 outline-zinc-800/70"} p-4 transition-all select-none ${isClickable ? "cursor-pointer hover:bg-zinc-700/50" : ""}`}
      onClick={href ? undefined : handleCardClick}
      onKeyDown={
        !href && isClickable
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") handleCardClick();
            }
          : undefined
      }
      role={!href && isClickable ? "button" : undefined}
      tabIndex={!href && isClickable ? 0 : undefined}
    >
      {href && (
        <SiteLink
          href={href}
          aria-label={title}
          className="absolute inset-0 z-[1] rounded-3xl"
        />
      )}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">{renderToolIcons()}</div>
        <div className="flex items-center gap-2">
          {resolvedMissingIntegrations?.length ? (
            // The warning replaces the activation badge: a workflow with
            // unconnected integrations can't run, so its activated/deactivated
            // state is moot until they're connected.
            <MissingIntegrationsWarning
              missingIntegrations={resolvedMissingIntegrations}
            />
          ) : (
            shouldShowActivation &&
            workflow && <ActivationStatus activated={workflow.activated} />
          )}
        </div>
      </div>

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

      <div className="mt-auto">
        <div className="mt-1 flex items-center justify-between gap-2">
          <div className="min-w-0 space-y-1">
            {shouldShowCreator && creator && (
              <CreatorAvatar
                creator={creator}
                showName
                loading={imageLoading}
              />
            )}

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
            {workflow?.is_system_workflow && <SystemWorkflowChip />}

            {resolvedAction !== "none" && (
              <span
                className="relative z-[2]"
                // Keep Run/Create presses from also triggering the card-level
                // open/select handler via click/key bubbling.
                onClick={(e) => e.stopPropagation()}
                onKeyDown={(e) => e.stopPropagation()}
              >
                <WorkflowActionButton
                  label={buttonConfig.label}
                  isPending={isLoading}
                  onPress={handlePrimaryAction}
                  variant={buttonConfig.variant}
                />
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );

  return showDescriptionAsTooltip ? (
    <Tooltip delay={200} closeDelay={0}>
      <Tooltip.Trigger className="block w-full">{cardContent}</Tooltip.Trigger>
      <Tooltip.Content
        placement="top"
        showArrow
        className={overlayVariants({
          surface: "raised",
          className: "max-w-xs rounded-3xl",
        })}
      >
        <div className="p-2">{workflow?.prompt || displayDescription}</div>
      </Tooltip.Content>
    </Tooltip>
  ) : (
    cardContent
  );
}

// Resolve the card's display data and settings from the various supported prop
// shapes (full Workflow, CommunityWorkflow, or simplified direct props).
function deriveWorkflowCardConfig(props: UnifiedWorkflowCardProps) {
  const {
    workflow,
    communityWorkflow,
    useCase,
    title: propTitle,
    description: propDescription,
    steps: propSteps,
    variant = "explore",
    showTrigger,
    showActivationStatus = false,
    showCreator,
    primaryAction,
    onCardClick,
    href,
    missingIntegrations: propMissingIntegrations,
  } = props;

  const title =
    propTitle ||
    useCase?.title ||
    workflow?.title ||
    communityWorkflow?.title ||
    "";
  const displayDescription =
    propDescription ||
    useCase?.description ||
    workflow?.description ||
    communityWorkflow?.description ||
    "";
  const steps =
    propSteps ||
    useCase?.steps ||
    workflow?.steps ||
    communityWorkflow?.steps ||
    [];
  const customIcon = useCase?.icon ?? workflow?.icon ?? communityWorkflow?.icon;
  const customIconColor =
    useCase?.icon_color ??
    workflow?.icon_color ??
    communityWorkflow?.icon_color;
  const totalExecutions =
    useCase?.total_executions ??
    workflow?.total_executions ??
    communityWorkflow?.total_executions ??
    0;
  const creator =
    useCase?.creator || communityWorkflow?.creator || workflow?.creator;

  const shouldShowTrigger = showTrigger ?? (variant === "user" && !!workflow);
  // A byline credits a community author; our own workflows don't need one.
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
    useCase?.system_workflow_key ??
    communityWorkflow?.system_workflow_key ??
    undefined;
  const sourceTriggerConfig =
    useCase?.trigger_config ?? communityWorkflow?.trigger_config ?? undefined;

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

// Helper function to determine default action based on variant
function getDefaultAction(variant: WorkflowVariant): WorkflowCardAction {
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
  action: WorkflowCardAction,
  customLabel?: string,
  propActionType?: "prompt" | "workflow",
): { label: string; variant: "primary" | "accent-soft" } {
  if (customLabel) {
    return { label: customLabel, variant: "primary" };
  }

  // Handle prompt vs workflow action type
  if (propActionType === "prompt") {
    return { label: "Insert Prompt", variant: "primary" };
  }

  switch (action) {
    case "run":
      return { label: "Run", variant: "accent-soft" };
    case "create":
      return { label: "Create", variant: "primary" };
    case "insert-prompt":
      return { label: "Insert Prompt", variant: "primary" };
    case "navigate":
      return { label: "View", variant: "accent-soft" };
    default:
      return { label: "Try", variant: "primary" };
  }
}

// Unified action button component
interface WorkflowActionButtonProps {
  label: string;
  isPending: boolean;
  onPress: (e: React.MouseEvent) => void;
  variant?: "primary" | "accent-soft";
  size?: "sm" | "md";
}

function WorkflowActionButton({
  label,
  isPending,
  onPress,
  variant = "primary",
  size = "sm",
}: WorkflowActionButtonProps) {
  return (
    <GaiaButton
      size={size}
      shape="md"
      variant={variant}
      className="font-medium"
      isPending={isPending}
      onPress={(e) => onPress(e as unknown as React.MouseEvent)}
    >
      {label}
    </GaiaButton>
  );
}

"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Tooltip } from "@heroui/tooltip";
import Image from "next/image";

import { CursorMagicSelection03Icon } from "@/components";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { Mail01Icon, PlayIcon, Timer02Icon, UserIcon } from '@/icons';
import { formatRunCount } from "@/utils/formatters";

import { Workflow } from "../../api/workflowApi";

// Utility function for calculating next run display
export function getNextRunDisplay(workflow: Workflow): string | null {
  const { trigger_config } = workflow;

  if (trigger_config.type === "schedule" && trigger_config.next_run) {
    const nextRun = new Date(trigger_config.next_run);
    const now = new Date();

    // Check if next run is in the future
    if (nextRun > now) {
      const diffMs = nextRun.getTime() - now.getTime();
      const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
      const diffDays = Math.floor(diffHours / 24);

      if (diffDays > 0) {
        return `Next run in ${diffDays}d`;
      } else if (diffHours > 0) {
        return `Next run in ${diffHours}h`;
      } else {
        return "Running soon";
      }
    }
  }

  return null;
}

// Reusable Trigger Icon Component
interface TriggerIconProps {
  triggerType: string;
  integrationId?: string;
  size?: number;
}

export function TriggerIcon({
  triggerType,
  integrationId,
  size = 15,
}: TriggerIconProps) {
  // Try to get icon from integrationId first
  if (integrationId) {
    const icon = getToolCategoryIcon(integrationId, {
      width: size,
      height: size,
      showBackground: false,
    });
    if (icon) {
      return <div className="flex items-center">{icon}</div>;
    }
  }

  // Use getToolCategoryIcon for integration-based triggers like gmail
  const categoryIcon = getToolCategoryIcon(triggerType, {
    width: size,
    height: size,
    showBackground: false,
  });

  if (categoryIcon) {
    return <div className="flex items-center">{categoryIcon}</div>;
  }

  // Fallback icons for basic trigger types
  switch (triggerType) {
    case "schedule":
      return <Timer02Icon width={size} height={size} />;
    case "manual":
      return <CursorMagicSelection03Icon width={size} height={size} />;
    default:
      return <Mail01Icon width={size} height={size} />;
  }
}

// Reusable Trigger Display Component
interface TriggerDisplayProps {
  triggerType: string;
  triggerLabel: string;
  integrationId?: string;
  nextRunText?: string;
  className?: string;
}

export function TriggerDisplay({
  triggerType,
  triggerLabel,
  integrationId,
  nextRunText,
  className = "",
}: TriggerDisplayProps) {
  return (
    <div className={`flex flex-wrap items-center gap-2 ${className}`}>
      <div className="flex items-center gap-1 text-xs text-zinc-500">
        <div className="w-4">
          <TriggerIcon
            triggerType={triggerType}
            integrationId={integrationId}
            size={15}
          />
        </div>
        {triggerLabel}
      </div>

      {nextRunText && (
        <div className="flex items-center gap-1 text-xs text-zinc-500">
          <Timer02Icon width={15} height={15} />
          {nextRunText}
        </div>
      )}
    </div>
  );
}

// Reusable Run Count Component
interface RunCountDisplayProps {
  totalExecutions: number;
  className?: string;
}

export function RunCountDisplay({
  totalExecutions,
  className = "",
}: RunCountDisplayProps) {
  return (
    <div
      className={`flex items-center gap-1 text-xs text-zinc-500 ${className}`}
    >
      <PlayIcon width={15} height={15} className="w-4 text-zinc-500" />
      {formatRunCount(totalExecutions)}
    </div>
  );
}

// Reusable Run Workflow Button
interface RunWorkflowButtonProps {
  isLoading: boolean;
  onPress: () => void;
  size?: "sm" | "md" | "lg";
  variant?: "flat" | "solid" | "bordered" | "light" | "ghost";
  className?: string;
}

export function RunWorkflowButton({
  isLoading,
  onPress,
  size = "sm",
  variant = "flat",
  className = "",
}: RunWorkflowButtonProps) {
  return (
    <Button
      color="primary"
      size={size}
      isLoading={isLoading}
      onPress={onPress}
      variant={variant}
      className={`text-primary ${className}`}
    >
      Run Workflow
    </Button>
  );
}

// Reusable Create Workflow Button
interface CreateWorkflowButtonProps {
  isLoading: boolean;
  onPress: () => void;
  size?: "sm" | "md" | "lg";
  variant?: "flat" | "solid" | "bordered" | "light" | "ghost";
  className?: string;
}

export function CreateWorkflowButton({
  isLoading,
  onPress,
  size = "sm",
  variant = "flat",
  className = "",
}: CreateWorkflowButtonProps) {
  return (
    <Button
      color="primary"
      size={size}
      variant={variant}
      className={`text-primary ${className}`}
      isLoading={isLoading}
      onPress={onPress}
    >
      Create
    </Button>
  );
}

// Reusable Activation Status Chip
interface ActivationStatusProps {
  activated: boolean;
  size?: "sm" | "md" | "lg";
}

export function ActivationStatus({
  activated,
  size = "sm",
}: ActivationStatusProps) {
  const color = activated ? "success" : "danger";
  const label = activated ? "Activated" : "Deactivated";

  return (
    <Chip color={color} variant="flat" size={size} radius="sm">
      {label}
    </Chip>
  );
}

// Reusable Creator Avatar
interface CreatorAvatarProps {
  creator: {
    name: string;
    avatar?: string;
  };
  size?: number;
  showTooltip?: boolean;
}

export function CreatorAvatar({
  creator,
  size = 27,
  showTooltip = true,
}: CreatorAvatarProps) {
  const avatar = (
    <div className="flex items-center gap-2">
      <div className="flex h-8 w-8 items-center justify-center rounded-full">
        {creator.avatar ? (
          <Image
            src={creator.avatar}
            alt={creator.name}
            width={size}
            height={size}
            className="rounded-full"
          />
        ) : (
          <UserIcon className="h-4 w-4 text-zinc-400" />
        )}
      </div>
    </div>
  );

  if (!showTooltip) return avatar;

  return (
    <Tooltip
      content={`Created by ${creator.name}`}
      showArrow
      closeDelay={0}
      delay={0}
      placement="left"
      color="foreground"
    >
      {avatar}
    </Tooltip>
  );
}

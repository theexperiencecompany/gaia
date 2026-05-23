"use client";

import { Chip } from "@heroui/chip";
import { Tooltip } from "@heroui/tooltip";
import {
  CursorMagicSelection03Icon,
  DateTimeIcon,
  Mail01Icon,
  UserCircle02Icon,
} from "@icons";
import Image from "next/image";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import {
  resolveCreatorAvatar,
  resolveCreatorName,
} from "@/features/workflows/utils/creator";
import { cn } from "@/lib/utils";

import type { Workflow } from "../../api/workflowApi";

/**
 * Get relative time display (e.g., "in 2h", "in 3d")
 */
function getRelativeTime(nextRun: Date, now: Date): string {
  const diffMs = nextRun.getTime() - now.getTime();
  const totalMinutes = Math.floor(diffMs / (1000 * 60));
  const totalHours = Math.floor(totalMinutes / 60);
  const totalDays = Math.floor(totalHours / 24);

  const remHours = totalHours % 24;
  const remMinutes = totalMinutes % 60;

  if (totalDays > 0) {
    return remHours > 0 ? `in ${totalDays}d ${remHours}h` : `in ${totalDays}d`;
  } else if (totalHours > 0) {
    return remMinutes > 0
      ? `in ${totalHours}h ${remMinutes}m`
      : `in ${totalHours}h`;
  } else if (totalMinutes > 0) {
    return `in ${totalMinutes}m`;
  } else {
    return "soon";
  }
}

// Utility function for calculating next run relative time display
export function getNextRunDisplay(workflow: Workflow): string | null {
  const { trigger_config } = workflow;

  if (trigger_config.type === "schedule" && trigger_config.next_run) {
    const nextRunValue = trigger_config.next_run as string;
    const nextRun = new Date(nextRunValue);
    const now = new Date();

    // Check if next run is in the future
    if (nextRun > now) {
      // Return only the relative time — the trigger label already shows
      // the scheduled time in the user's local timezone, so we avoid
      // displaying the same time twice.
      return getRelativeTime(nextRun, now);
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

function TriggerIcon({
  triggerType,
  integrationId,
  size = 20,
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
      return <DateTimeIcon width={size} height={size} />;
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
  if (triggerLabel === "Manual Trigger" || !triggerLabel) {
    return (
      <Chip size="sm" variant="flat" radius="sm" className="text-xs">
        Manual
      </Chip>
    );
  }

  return (
    <div
      className={cn("flex items-center gap-1 text-xs text-zinc-500", className)}
    >
      <div className="w-4">
        <TriggerIcon
          triggerType={triggerType}
          integrationId={integrationId}
          size={16}
        />
      </div>
      <span>
        {triggerLabel}
        {nextRunText ? ` (${nextRunText})` : ""}
      </span>
    </div>
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

interface SystemWorkflowChipProps {
  size?: "sm" | "md" | "lg";
}

export function SystemWorkflowChip({ size = "sm" }: SystemWorkflowChipProps) {
  return (
    <Tooltip
      content="Automatically created by GAIA when you connected this integration"
      placement="top"
      delay={300}
      closeDelay={0}
      classNames={{ content: "bg-zinc-800 text-xs max-w-48 text-center" }}
    >
      <Chip
        color="primary"
        variant="flat"
        size={size}
        className="text-primary"
        startContent={
          <Image src="/brand/gaia_logo.svg" alt="GAIA" width={14} height={14} />
        }
      >
        <span className="pl-0.5">System</span>
      </Chip>
    </Tooltip>
  );
}

// Reusable Creator Avatar
interface CreatorAvatarProps {
  creator: {
    id: string;
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
  const avatarSrc = resolveCreatorAvatar(creator);
  const displayName = resolveCreatorName(creator);

  const avatar = (
    <div className="flex items-center gap-2">
      <div className="flex h-7 w-7 items-center justify-center rounded-full">
        {avatarSrc ? (
          <Image
            src={avatarSrc}
            alt={displayName}
            width={size}
            height={size}
            className="rounded-full h-7 w-7"
          />
        ) : (
          <UserCircle02Icon className="h-7 w-7 text-zinc-400" />
        )}
      </div>
    </div>
  );

  if (!showTooltip) return avatar;

  return (
    <Tooltip
      content={`Created by ${displayName}`}
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

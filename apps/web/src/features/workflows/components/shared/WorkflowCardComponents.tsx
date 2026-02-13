"use client";

import { Chip } from "@heroui/chip";
import { Tooltip } from "@heroui/tooltip";
import {
  CursorMagicSelection03Icon,
  DateTimeIcon,
  Mail01Icon,
  PlayIcon,
  TimeScheduleIcon,
  UserCircle02Icon,
} from "@icons";
import Image from "next/image";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { formatRunCount } from "@/utils/formatters";

import type { Workflow } from "../../api/workflowApi";
import { getBrowserTimezone } from "../../schemas/workflowFormSchema";

/**
 * Format a UTC date to a localized time string in the specified timezone.
 *
 * @param utcDate - Date object in UTC
 * @param timezone - IANA timezone name (e.g., "America/New_York") or offset string (e.g., "+05:30")
 * @returns Formatted time string like "9:00 AM" or "9:00 AM IST"
 */
function formatTimeInTimezone(utcDate: Date, timezone: string): string {
  try {
    // Check if timezone is an offset string like "+05:30" or "-08:00"
    const offsetMatch = timezone.match(/^([+-])(\d{2}):(\d{2})$/);

    if (offsetMatch) {
      // For offset strings, we can't use Intl directly with the offset
      // We need to manually calculate the time
      const sign = offsetMatch[1] === "+" ? 1 : -1;
      const hours = parseInt(offsetMatch[2], 10);
      const minutes = parseInt(offsetMatch[3], 10);
      const offsetMs = sign * (hours * 60 + minutes) * 60 * 1000;

      // Create a new date adjusted by the offset
      const localDate = new Date(utcDate.getTime() + offsetMs);

      // Format without timezone name since we only have an offset
      return localDate.toLocaleTimeString("en-US", {
        hour: "numeric",
        minute: "2-digit",
        hour12: true,
        timeZone: "UTC", // Use UTC since we already applied the offset
      });
    }

    // For IANA timezone names, use Intl.DateTimeFormat
    return utcDate.toLocaleTimeString("en-US", {
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
      timeZone: timezone,
      timeZoneName: "short",
    });
  } catch {
    // Fallback to browser timezone if the timezone is invalid
    return utcDate.toLocaleTimeString("en-US", {
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
      timeZoneName: "short",
    });
  }
}

/**
 * Get relative time display (e.g., "in 2h", "in 3d")
 */
function getRelativeTime(nextRun: Date, now: Date): string {
  const diffMs = nextRun.getTime() - now.getTime();
  const diffMinutes = Math.floor(diffMs / (1000 * 60));
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  const diffDays = Math.floor(diffHours / 24);

  if (diffDays > 0) {
    return `in ${diffDays}d`;
  } else if (diffHours > 0) {
    return `in ${diffHours}h`;
  } else if (diffMinutes > 0) {
    return `in ${diffMinutes}m`;
  } else {
    return "soon";
  }
}

// Utility function for calculating next run display
export function getNextRunDisplay(workflow: Workflow): string | null {
  const { trigger_config } = workflow;

  if (trigger_config.type === "schedule" && trigger_config.next_run) {
    const nextRunValue = trigger_config.next_run as string;
    const nextRun = new Date(nextRunValue);
    const now = new Date();

    // Check if next run is in the future
    if (nextRun > now) {
      // Get the workflow's stored timezone, fallback to browser timezone
      const workflowTimezone =
        (trigger_config.timezone as string) || getBrowserTimezone();

      // Format: "9:00 AM IST (in 2h)"
      const formattedTime = formatTimeInTimezone(nextRun, workflowTimezone);
      const relativeTime = getRelativeTime(nextRun, now);

      return `${formattedTime} (${relativeTime})`;
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
  if (triggerLabel !== "Manual Trigger")
    return (
      <div className={`flex flex-wrap items-center gap-2 ${className}`}>
        <div className="flex items-center gap-1 text-xs text-zinc-500">
          <div className="w-4">
            <TriggerIcon
              triggerType={triggerType}
              integrationId={integrationId}
              size={17}
            />
          </div>
          {triggerLabel}
        </div>

        {nextRunText && (
          <div className="flex items-center gap-1 text-xs text-zinc-500">
            <TimeScheduleIcon width={15} height={15} />
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
  const runCount = formatRunCount(totalExecutions);

  if (runCount !== "Never run")
    return (
      <div
        className={`flex items-center gap-1 text-xs text-zinc-500 ${className}`}
      >
        <PlayIcon width={15} height={15} className="w-4 text-zinc-500" />
        <span className="text-nowrap">{formatRunCount(totalExecutions)}</span>
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
  const avatar = (
    <div className="flex items-center gap-2">
      <div className="flex h-7 w-7 items-center justify-center rounded-full">
        {creator.avatar || creator.id === "system" ? (
          <Image
            src={creator.avatar || "/images/logos/experience_black_bg.png"}
            alt={creator.name}
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

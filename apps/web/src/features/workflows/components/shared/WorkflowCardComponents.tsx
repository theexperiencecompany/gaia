"use client";

import { ButtonGroup, Chip, Dropdown, Menu, Tooltip } from "@heroui/react";
import {
  Alert01Icon,
  ArrowDown01Icon,
  CursorMagicSelection03Icon,
  DateTimeIcon,
  Mail01Icon,
  UserCircle02Icon,
} from "@icons";
import Image from "next/image";
import { useState } from "react";
import {
  chipVariants,
  overlayVariants,
} from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { shapeVariants } from "@/components/shared/shape";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useIntegrationLookup } from "@/features/integrations/hooks/useIntegrationLookup";
import {
  resolveCreatorAvatar,
  resolveCreatorName,
} from "@/features/workflows/utils/creator";
import { cn } from "@/lib/utils";
import type { IntegrationRef } from "@/types/features/workflowTypes";
import type { ContentCreator } from "@/types/shared/contentTypes";
import { missingIntegrationsMessage } from "./workflowCardHelpers";

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
  const { getIntegrationIconUrl } = useIntegrationLookup();

  // Try to get icon from integrationId first (pass the integration's icon URL so
  // custom/MCP integration triggers resolve, not just built-ins).
  if (integrationId) {
    const icon = getToolCategoryIcon(
      integrationId,
      { width: size, height: size, showBackground: false },
      getIntegrationIconUrl(integrationId),
    );
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
      <Chip
        size="sm"
        variant="soft"
        className={shapeVariants({ shape: "sm", className: "text-xs" })}
      >
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
    <Chip
      className={shapeVariants({ shape: "sm" })}
      color={color}
      variant="soft"
      size={size}
    >
      {label}
    </Chip>
  );
}

interface SystemWorkflowChipProps {
  size?: "sm" | "md" | "lg";
}

export function SystemWorkflowChip({ size = "sm" }: SystemWorkflowChipProps) {
  return (
    <Tooltip delay={300} closeDelay={0}>
      <Tooltip.Trigger>
        <Chip
          color="accent"
          variant="soft"
          size={size}
          className={chipVariants({ hue: "brand" })}
        >
          <Image src="/brand/gaia_logo.svg" alt="GAIA" width={14} height={14} />
          <Chip.Label>System</Chip.Label>
        </Chip>
      </Tooltip.Trigger>
      <Tooltip.Content
        placement="top"
        className={overlayVariants({
          surface: "raised",
          className: "text-xs max-w-48 text-center",
        })}
      >
        Automatically created by GAIA when you connected this integration
      </Tooltip.Content>
    </Tooltip>
  );
}

// Reusable Creator Avatar
interface CreatorAvatarProps {
  creator: ContentCreator;
  size?: number;
  showTooltip?: boolean;
  /** Render the creator's name beside the avatar (verified when it's ours) */
  showName?: boolean;
}

export function CreatorAvatar({
  creator,
  size = 27,
  showTooltip = true,
  showName = false,
}: CreatorAvatarProps) {
  const avatarSrc = resolveCreatorAvatar(creator);
  const displayName = resolveCreatorName(creator);

  if (showName) {
    return (
      <div className="flex items-center gap-1.5">
        <div className="flex h-6 w-6 items-center justify-center overflow-hidden rounded-full">
          {avatarSrc ? (
            <Image
              src={avatarSrc}
              alt={displayName}
              width={100}
              height={100}
              className="object-contain"
            />
          ) : (
            <UserCircle02Icon className="h-4 w-4 text-zinc-400" />
          )}
        </div>
        <span className="truncate text-xs text-zinc-400">{displayName}</span>
      </div>
    );
  }

  const avatar = (
    <div className="flex items-center gap-2">
      <div className="flex h-7 w-7 items-center justify-center rounded-full">
        {avatarSrc ? (
          <Image
            src={avatarSrc}
            alt={displayName}
            width={size}
            height={size}
            className="rounded-full h-7 w-7 object-contain"
          />
        ) : (
          <UserCircle02Icon className="h-7 w-7 text-zinc-400" />
        )}
      </div>
    </div>
  );

  if (!showTooltip) return avatar;

  return (
    <Tooltip closeDelay={0} delay={0}>
      <Tooltip.Trigger>{avatar}</Tooltip.Trigger>
      <Tooltip.Content placement="left" showArrow>
        {`Created by ${displayName}`}
      </Tooltip.Content>
    </Tooltip>
  );
}

interface MissingIntegrationsWarningProps {
  missingIntegrations: IntegrationRef[];
}

/**
 * The status a workflow with unconnected integrations has instead of
 * activated/deactivated: it cannot run either way until they are connected.
 * Shaped like the activation chip it stands in for, and shared with the modal
 * header so the card and the modal can never disagree about the same workflow.
 */
export function NeedsSetupChip({ size = "sm" }: { size?: "sm" | "md" | "lg" }) {
  return (
    <Chip
      color="warning"
      variant="soft"
      size={size}
      className={shapeVariants({ shape: "sm", className: "cursor-default" })}
    >
      <Alert01Icon width={13} height={13} />
      <Chip.Label>Needs setup</Chip.Label>
    </Chip>
  );
}

export function MissingIntegrationsWarning({
  missingIntegrations,
}: Readonly<MissingIntegrationsWarningProps>) {
  if (!missingIntegrations.length) return null;

  return (
    <Tooltip delay={200} closeDelay={0}>
      <Tooltip.Trigger>
        <NeedsSetupChip />
      </Tooltip.Trigger>
      <Tooltip.Content
        placement="top"
        className={overlayVariants({
          surface: "raised",
          className: "text-xs max-w-56 text-center",
        })}
      >
        {missingIntegrationsMessage(missingIntegrations)}
      </Tooltip.Content>
    </Tooltip>
  );
}

interface MissingIntegrationsAlertProps {
  /** Integrations the workflow needs but the user hasn't connected. */
  missingIntegrations: IntegrationRef[];
  /** Id currently connecting (shows a spinner; disables the others). */
  connectingId: string | null;
  onConnect: (integrationId: string) => void;
}

/** Full banner version of {@link MissingIntegrationsWarning}: the same message
 *  plus a connect button per integration. Used in the workflow modal where
 *  there is room to act on it. */
export function MissingIntegrationsAlert({
  missingIntegrations,
  connectingId,
  onConnect,
}: Readonly<MissingIntegrationsAlertProps>) {
  const { getIntegrationIconUrl } = useIntegrationLookup();
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);

  if (!missingIntegrations.length) return null;

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-yellow-500/10 px-4 py-3 text-sm text-yellow-300">
      <span className="flex items-center gap-2">
        <Alert01Icon width={16} height={16} className="shrink-0" />
        <span>{missingIntegrationsMessage(missingIntegrations)}</span>
      </span>

      {missingIntegrations.length === 1 ? (
        <GaiaButton
          variant="warning-soft"
          size="sm"
          isPending={!!connectingId}
          isDisabled={!!connectingId}
          onPress={() => onConnect(missingIntegrations[0].id)}
        >
          Connect {missingIntegrations[0].name}
        </GaiaButton>
      ) : (
        <ButtonGroup size="sm">
          <GaiaButton
            variant="default-solid"
            isPending={!!connectingId}
            isDisabled={!!connectingId}
            onPress={() => setIsDropdownOpen((o) => !o)}
          >
            Connect Apps
          </GaiaButton>
          <Dropdown isOpen={isDropdownOpen} onOpenChange={setIsDropdownOpen}>
            <GaiaButton
              aria-label="More options"
              variant="default-solid"
              isIconOnly
              isDisabled={!!connectingId}
            >
              <ArrowDown01Icon className="size-3.5" />
            </GaiaButton>
            <Dropdown.Popover placement="bottom end">
              <Menu aria-label="Missing integrations to connect">
                {missingIntegrations.map((integration) => {
                  const iconUrl = getIntegrationIconUrl(integration.id);
                  return (
                    <Menu.Item
                      key={integration.id}
                      id={integration.id}
                      textValue={`Connect ${integration.name}`}
                      onAction={() => onConnect(integration.id)}
                    >
                      {iconUrl && (
                        <Image
                          src={iconUrl}
                          alt={integration.name}
                          width={16}
                          height={16}
                          className="rounded-sm"
                        />
                      )}
                      Connect {integration.name}
                    </Menu.Item>
                  );
                })}
              </Menu>
            </Dropdown.Popover>
          </Dropdown>
        </ButtonGroup>
      )}
    </div>
  );
}

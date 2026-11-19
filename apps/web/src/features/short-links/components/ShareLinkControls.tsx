"use client";

import { Dropdown, DropdownMenu, DropdownPopover } from "@heroui/react";
import { Share08Icon } from "@icons";
import type { KeyboardEvent, MouseEvent } from "react";

import { GaiaButton } from "@/components/shared/GaiaButton";
import { ShareLinkSettingsModal } from "@/features/short-links/components/ShareLinkSettingsModal";
import { shareLinkMenuItems } from "@/features/short-links/components/shareLinkMenuItems";
import { useShareLink } from "@/features/short-links/hooks/useShareLink";
import type { LinkTarget } from "@/types/features/shortLinkTypes";

interface ShareLinkControlsProps {
  target: LinkTarget;
  /** A bare icon trigger for dense rows and toolbars; a labelled "Share" button otherwise. */
  iconOnly?: boolean;
}

function stopPropagation(event: MouseEvent | KeyboardEvent) {
  event.stopPropagation();
}

/**
 * One "Share" menu for an artifact's public heygaia.link: copy it (sharing it
 * if it isn't yet), change who it opens for, or stop sharing it once it is. Stops press propagation so
 * it can sit inside a pressable card or row without also opening it.
 */
export function ShareLinkControls({
  target,
  iconOnly = false,
}: ShareLinkControlsProps) {
  const share = useShareLink(target);

  return (
    <span
      role="presentation"
      className="flex items-center"
      onClick={stopPropagation}
      onKeyDown={stopPropagation}
    >
      <Dropdown onOpenChange={share.onMenuOpenChange}>
        <GaiaButton
          size="sm"
          variant={iconOnly ? "ghost" : "default-soft"}
          isIconOnly={iconOnly}
          aria-label="Share"
          isPending={share.pending !== null}
        >
          <Share08Icon size={16} />
          {iconOnly ? null : "Share"}
        </GaiaButton>
        <DropdownPopover placement="bottom end" className="max-w-72">
          <DropdownMenu aria-label="Share">
            {shareLinkMenuItems(share)}
          </DropdownMenu>
        </DropdownPopover>
      </Dropdown>
      <ShareLinkSettingsModal share={share} />
    </span>
  );
}

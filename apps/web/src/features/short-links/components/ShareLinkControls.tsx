"use client";

import { Button } from "@heroui/button";
import { Dropdown, DropdownMenu, DropdownTrigger } from "@heroui/dropdown";
import { Share08Icon } from "@icons";
import type { KeyboardEvent, MouseEvent } from "react";

import { shareLinkMenuItems } from "@/features/short-links/components/shareLinkMenuItems";
import { useShareLink } from "@/features/short-links/hooks/useShareLink";
import type { ShortLinkTargetType } from "@/types/features/shortLinkTypes";

interface ShareLinkControlsProps {
  targetType: ShortLinkTargetType;
  targetId: string;
  /** What stopping cannot take back, shown before and after stopping. */
  stopWarning?: string;
  /** A bare icon trigger for dense rows and toolbars; a labelled "Share" button otherwise. */
  iconOnly?: boolean;
}

function stopPropagation(event: MouseEvent | KeyboardEvent) {
  event.stopPropagation();
}

/**
 * One "Share" menu for an artifact's public heygaia.link: copy it (sharing it
 * if it isn't yet), or stop sharing it once it is. Stops press propagation so
 * it can sit inside a pressable card or row without also opening it.
 */
export function ShareLinkControls({
  targetType,
  targetId,
  stopWarning,
  iconOnly = false,
}: ShareLinkControlsProps) {
  const share = useShareLink(targetType, targetId, stopWarning);

  return (
    <span
      role="presentation"
      className="flex items-center"
      onClick={stopPropagation}
      onKeyDown={stopPropagation}
    >
      <Dropdown placement="bottom-end" onOpenChange={share.onMenuOpenChange}>
        <DropdownTrigger>
          <Button
            size="sm"
            variant={iconOnly ? "light" : "flat"}
            isIconOnly={iconOnly}
            aria-label="Share"
            isLoading={share.pending !== null}
            startContent={iconOnly ? undefined : <Share08Icon size={16} />}
          >
            {iconOnly ? <Share08Icon size={16} /> : "Share"}
          </Button>
        </DropdownTrigger>
        <DropdownMenu
          aria-label="Share"
          className="max-w-72"
          itemClasses={{ description: "whitespace-normal" }}
        >
          {shareLinkMenuItems(share, stopWarning)}
        </DropdownMenu>
      </Dropdown>
    </span>
  );
}

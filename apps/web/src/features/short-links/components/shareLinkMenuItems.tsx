import { Description, DropdownItem, Label } from "@heroui/react";
import { Link01Icon, Settings01Icon, Unlink01Icon } from "@icons";
import type { ReactElement } from "react";

import type { ShareLink } from "@/features/short-links/hooks/useShareLink";

/**
 * The share entries of a menu: "Copy link", "Share settings", plus "Stop
 * sharing" only while a live link exists. A plain function, not a component,
 * because a menu's collection takes its items as direct children; whoever
 * renders the menu also renders ShareLinkSettingsModal for the hook.
 */
export function shareLinkMenuItems(
  share: ShareLink,
  stopWarning?: string,
): ReactElement[] {
  const items: ReactElement[] = [
    <DropdownItem
      key="copy-link"
      id="copy-link"
      textValue="Copy link"
      onAction={share.copyLink}
    >
      <Link01Icon size={16} />
      <Label>Copy link</Label>
    </DropdownItem>,
    <DropdownItem
      key="share-settings"
      id="share-settings"
      textValue="Share settings"
      onAction={share.openSettings}
    >
      <Settings01Icon size={16} />
      <Label>Share settings</Label>
    </DropdownItem>,
  ];
  if (share.isShared) {
    items.push(
      <DropdownItem
        key="stop-sharing"
        id="stop-sharing"
        textValue="Stop sharing"
        variant="danger"
        onAction={share.stopSharing}
      >
        <Unlink01Icon size={16} />
        <Label>Stop sharing</Label>
        {stopWarning && (
          <Description className="whitespace-normal">{stopWarning}</Description>
        )}
      </DropdownItem>,
    );
  }
  return items;
}

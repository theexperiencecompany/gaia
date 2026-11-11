import { DropdownItem } from "@heroui/dropdown";
import { Link01Icon, Unlink01Icon } from "@icons";
import type { CollectionElement } from "@react-types/shared";

import type { ShareLink } from "@/features/short-links/hooks/useShareLink";

/**
 * The share entries of a menu: "Copy link", plus "Stop sharing" only while a
 * live link exists. A plain function, not a component, because a DropdownMenu
 * only accepts DropdownItems as its direct children.
 */
export function shareLinkMenuItems(
  share: ShareLink,
  stopWarning?: string,
): CollectionElement<object>[] {
  const items: CollectionElement<object>[] = [
    <DropdownItem
      key="copy-link"
      startContent={<Link01Icon size={16} />}
      onPress={share.copyLink}
    >
      Copy link
    </DropdownItem>,
  ];
  if (share.isShared) {
    items.push(
      <DropdownItem
        key="stop-sharing"
        color="danger"
        description={stopWarning}
        startContent={<Unlink01Icon size={16} />}
        onPress={share.stopSharing}
      >
        Stop sharing
      </DropdownItem>,
    );
  }
  return items;
}

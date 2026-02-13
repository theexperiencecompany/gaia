"use client";
import { Button } from "@heroui/button";
import { Tooltip } from "@heroui/tooltip";

import {
  Archive01Icon,
  Cancel01Icon,
  CheckmarkSquare03Icon,
  Delete02Icon,
  SquareIcon,
  StarIcon,
} from "@/icons";

interface SelectionToolbarProps {
  selectedCount: number;
  onClear: () => void;
  onBulkMarkAsRead: () => void;
  onBulkMarkAsUnread: () => void;
  onBulkStar: () => void;
  onBulkArchive: () => void;
  onBulkTrash: () => void;
}

export function SelectionToolbar({
  selectedCount,
  onClear,
  onBulkMarkAsRead,
  onBulkMarkAsUnread,
  onBulkStar,
  onBulkArchive,
  onBulkTrash,
}: SelectionToolbarProps) {
  return (
    <div className="flex items-center justify-between rounded-md bg-zinc-900 px-1 py-1 text-white backdrop-blur-xl">
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          color="default"
          variant="flat"
          onPress={onClear}
          startContent={<Cancel01Icon size={16} />}
        >
          Clear selection
        </Button>
        <span className="font-medium">{selectedCount} selected</span>
      </div>
      <div className="flex items-center gap-2">
        <Tooltip content="Mark as read">
          <Button
            size="sm"
            color="default"
            variant="light"
            onPress={onBulkMarkAsRead}
            isIconOnly
          >
            <CheckmarkSquare03Icon size={16} />
          </Button>
        </Tooltip>
        <Tooltip content="Mark as unread">
          <Button
            size="sm"
            color="default"
            variant="light"
            onPress={onBulkMarkAsUnread}
            isIconOnly
          >
            <SquareIcon size={16} />
          </Button>
        </Tooltip>
        <Tooltip content="Star">
          <Button
            size="sm"
            color="warning"
            variant="light"
            onPress={onBulkStar}
            isIconOnly
          >
            <StarIcon size={16} />
          </Button>
        </Tooltip>
        <Tooltip content="Archive">
          <Button
            size="sm"
            color="default"
            variant="light"
            onPress={onBulkArchive}
            isIconOnly
          >
            <Archive01Icon size={16} />
          </Button>
        </Tooltip>
        <Tooltip content="Move to trash">
          <Button
            size="sm"
            color="danger"
            variant="light"
            onPress={onBulkTrash}
            isIconOnly
          >
            <Delete02Icon size={16} />
          </Button>
        </Tooltip>
      </div>
    </div>
  );
}

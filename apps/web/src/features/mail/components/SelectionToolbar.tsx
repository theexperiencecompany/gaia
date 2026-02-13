"use client";
import { Button } from "@heroui/button";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
  useDisclosure,
} from "@heroui/modal";
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
  onBulkUnstar: () => void;
  onBulkArchive: () => void;
  onBulkTrash: () => void;
}

export function SelectionToolbar({
  selectedCount,
  onClear,
  onBulkMarkAsRead,
  onBulkMarkAsUnread,
  onBulkStar,
  onBulkUnstar,
  onBulkArchive,
  onBulkTrash,
}: SelectionToolbarProps) {
  const { isOpen, onOpen, onClose } = useDisclosure();

  const handleConfirmTrash = () => {
    onBulkTrash();
    onClose();
  };

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-md bg-zinc-900 px-1 py-1 text-white backdrop-blur-xl">
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
              aria-label="Mark as read"
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
              aria-label="Mark as unread"
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
              aria-label="Star"
            >
              <StarIcon size={16} />
            </Button>
          </Tooltip>
          <Tooltip content="Unstar">
            <Button
              size="sm"
              color="default"
              variant="flat"
              onPress={onBulkUnstar}
              isIconOnly
              aria-label="Unstar"
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
              aria-label="Archive"
            >
              <Archive01Icon size={16} />
            </Button>
          </Tooltip>
          <Tooltip content="Move to trash">
            <Button
              size="sm"
              color="danger"
              variant="light"
              onPress={onOpen}
              isIconOnly
              aria-label="Move to trash"
            >
              <Delete02Icon size={16} />
            </Button>
          </Tooltip>
        </div>
      </div>

      <Modal isOpen={isOpen} onOpenChange={onClose} size="sm">
        <ModalContent>
          <ModalHeader>Confirm Delete</ModalHeader>
          <ModalBody>
            <p>
              Are you sure you want to move {selectedCount} email
              {selectedCount > 1 ? "s" : ""} to trash?
            </p>
          </ModalBody>
          <ModalFooter>
            <Button variant="light" onPress={onClose}>
              Cancel
            </Button>
            <Button color="danger" onPress={handleConfirmTrash}>
              Move to Trash
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </>
  );
}

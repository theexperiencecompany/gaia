"use client";

import { Button } from "@heroui/button";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/dropdown";
import { Input } from "@heroui/input";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import { useRouter } from "next/navigation";
import {
  type ReactNode,
  type SetStateAction,
  useCallback,
  useState,
} from "react";

import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import { chatApi } from "@/features/chat/api/chatApi";
import { useConfirmation } from "@/hooks/useConfirmation";
import { useDeleteConversation } from "@/hooks/useDeleteConversation";
import {
  ArrowDown01Icon,
  Delete02Icon,
  MessageNotificationIcon,
  MoreVerticalIcon,
  PencilEdit02Icon,
  StarIcon,
} from "@/icons";
import { db } from "@/lib/db/chatDb";
import { useChatStore } from "@/stores/chatStore";

export default function ChatOptionsDropdown({
  buttonHovered,
  chatId,
  chatName,
  starred = false,
  isUnread = false,
  logo2 = false,
  btnChildren = undefined,
}: {
  buttonHovered: boolean;
  chatId: string;
  chatName: string;
  starred: boolean | undefined;
  isUnread?: boolean;
  logo2?: boolean;
  btnChildren?: ReactNode;
}) {
  const deleteConversation = useDeleteConversation();
  const { confirm, confirmationProps } = useConfirmation();
  const [dangerStateHovered, setDangerStateHovered] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [newName, setNewName] = useState(chatName);
  const router = useRouter();

  const handleStarToggle = async () => {
    const newStarredValue = starred === undefined ? true : !starred;

    try {
      // Make the API call first
      await chatApi.toggleStarConversation(chatId, newStarredValue);

      // Update IndexedDB atomically - event will update Zustand store
      await db.updateConversationFields(chatId, {
        starred: newStarredValue,
      });
    } catch (error) {
      console.error("Failed to update star", error);
    }
  };

  const handleReadToggle = async () => {
    const newIsUnread = !isUnread;

    // Optimistic update - update store immediately for instant UI feedback
    useChatStore
      .getState()
      .updateConversation(chatId, { isUnread: newIsUnread });

    try {
      // Also update IndexedDB for persistence
      await db.updateConversationFields(chatId, { isUnread: newIsUnread });

      // API call in background
      if (newIsUnread) {
        chatApi.markAsUnread(chatId).catch(console.error);
      } else {
        chatApi.markAsRead(chatId).catch(console.error);
      }
    } catch (error) {
      // Revert on error
      useChatStore
        .getState()
        .updateConversation(chatId, { isUnread: isUnread });
      console.error("Failed to toggle read status", error);
    }
  };

  const closeEditModal = useCallback(() => {
    setIsEditModalOpen(false);
    setNewName(""); // Clear the input field
  }, []);

  const handleEdit = async () => {
    if (!newName) return;
    try {
      await chatApi.renameConversation(chatId, newName);

      // Update IndexedDB atomically - event will update Zustand store
      await db.updateConversationFields(chatId, {
        title: newName,
        description: newName,
      });

      closeEditModal();
    } catch (error) {
      console.error("Failed to update chat name", error);
    }
  };

  const handleDelete = useCallback(async () => {
    const confirmed = await confirm({
      title: "Delete Chat",
      message:
        "Are you sure you want to delete this chat? This action cannot be undone.",
      confirmText: "Delete",
      cancelText: "Cancel",
      variant: "destructive",
    });

    if (!confirmed) return;

    try {
      router.push("/c");
      await deleteConversation(chatId);
    } catch (error) {
      console.error("Failed to delete chat", error);
    }
  }, [router, chatId, deleteConversation, confirm]);

  const openEditModal = () => {
    setNewName(chatName); // Reset to current chat name when opening edit modal
    setIsEditModalOpen(true);
  };

  return (
    <>
      <Dropdown
        className={`group/${chatId} w-fit min-w-fit text-foreground dark`}
        size="sm"
      >
        <DropdownTrigger>
          <Button
            className={`ml-auto ${buttonHovered ? "backdrop-blur-lg" : ""}`}
            isIconOnly={!btnChildren}
            variant={btnChildren ? "flat" : "light"}
            radius={btnChildren ? "md" : "full"}
            // size={btnChildren ? "md" : "sm"}
            size="sm"
          >
            {btnChildren}
            {logo2 ? (
              <ArrowDown01Icon width={25} />
            ) : (
              <MoreVerticalIcon
                className={
                  "transition-all " +
                  (buttonHovered
                    ? "opacity-100"
                    : "w-[20px] min-w-[20px] opacity-0")
                }
                width={20}
              />
            )}
          </Button>
        </DropdownTrigger>
        <DropdownMenu aria-label="Static Actions">
          <DropdownItem key="star" textValue="Star" onPress={handleStarToggle}>
            <div className="flex flex-row items-center justify-start gap-2">
              <StarIcon color="white" width={18} height={18} />
              {starred ? "Unstar" : "Star"}
            </div>
          </DropdownItem>
          <DropdownItem key="edit" textValue="Rename" onPress={openEditModal}>
            <div className="flex flex-row items-center justify-start gap-2">
              <PencilEdit02Icon color="white" width={18} height={18} />
              Rename
            </div>
          </DropdownItem>
          <DropdownItem
            key="read"
            textValue={isUnread ? "Mark as read" : "Mark as unread"}
            onPress={handleReadToggle}
          >
            <div className="flex flex-row items-center justify-start gap-2">
              <MessageNotificationIcon color="white" width={18} height={18} />
              {isUnread ? "Mark as read" : "Mark as unread"}
            </div>
          </DropdownItem>
          <DropdownItem
            key="delete"
            className="text-danger"
            color="danger"
            textValue="Delete"
            onMouseOut={() => setDangerStateHovered(false)}
            onMouseOver={() => setDangerStateHovered(true)}
            onPress={handleDelete}
          >
            <div className="flex flex-row items-center justify-start gap-2">
              <Delete02Icon
                color={dangerStateHovered ? "white" : "red"}
                width={18}
                height={18}
              />
              Delete
            </div>
          </DropdownItem>
        </DropdownMenu>
      </Dropdown>

      <Modal
        className="text-foreground dark"
        isOpen={isEditModalOpen}
        onOpenChange={closeEditModal}
      >
        <ModalContent>
          <ModalHeader className="pb-0">Rename Conversation</ModalHeader>
          <ModalBody>
            <Input
              label={
                <div className="space-x-1 text-xs">
                  <span>Previous Name:</span>
                  <span className="text-red-500">{chatName}</span>
                </div>
              }
              labelPlacement="outside"
              placeholder="Enter new chat name"
              size="lg"
              type="text"
              value={newName}
              variant="faded"
              onChange={(e: { target: { value: SetStateAction<string> } }) =>
                setNewName(e.target.value)
              }
              onKeyDown={(e: { key: string }) => {
                if (e.key === "Enter") handleEdit();
              }}
            />
          </ModalBody>
          <ModalFooter>
            <Button variant="light" onPress={closeEditModal}>
              Cancel
            </Button>
            <Button color="primary" onPress={handleEdit}>
              Save
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>

      <ConfirmationDialog {...confirmationProps} />
    </>
  );
}

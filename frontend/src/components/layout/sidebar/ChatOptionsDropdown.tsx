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
import { DotsVerticalIcon } from "@radix-ui/react-icons";
import { ChevronDown, Star, Trash } from "lucide-react";
import { useRouter } from "next/navigation";
import { ReactNode, SetStateAction, useCallback, useState } from "react";

import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import { PencilRenameIcon } from "@/components/shared/icons";
import { chatApi } from "@/features/chat/api/chatApi";
import { useFetchConversations } from "@/features/chat/hooks/useConversationList";
import { useConfirmation } from "@/hooks/useConfirmation";
import { useDeleteConversation } from "@/hooks/useDeleteConversation";
import { db } from "@/lib/db/chatDb";
import { useChatStore } from "@/stores/chatStore";

export default function ChatOptionsDropdown({
  buttonHovered,
  chatId,
  chatName,
  starred = false,
  logo2 = false,
  btnChildren = undefined,
}: {
  buttonHovered: boolean;
  chatId: string;
  chatName: string;
  starred: boolean | undefined;
  logo2?: boolean;
  btnChildren?: ReactNode;
}) {
  const fetchConversations = useFetchConversations();
  const deleteConversation = useDeleteConversation();
  const { confirm, confirmationProps } = useConfirmation();
  const updateConversation = useChatStore((state) => state.updateConversation);
  const [dangerStateHovered, setDangerStateHovered] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [newName, setNewName] = useState(chatName);
  const router = useRouter();

  const handleStarToggle = async () => {
    const newStarredValue = starred === undefined ? true : !starred;

    try {
      // Optimistically update the UI
      updateConversation(chatId, { starred: newStarredValue });

      // Make the API call
      await chatApi.toggleStarConversation(chatId, newStarredValue);

      const conversation = await db.getConversation(chatId);
      if (conversation) {
        await db.putConversation({
          ...conversation,
          starred: newStarredValue,
          updatedAt: new Date(),
        });
      }

      await fetchConversations();
    } catch (error) {
      console.error("Failed to update star", error);
      // Revert the optimistic update on error
      updateConversation(chatId, { starred: !newStarredValue });
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

      const conversation = await db.getConversation(chatId);
      if (conversation) {
        await db.putConversation({
          ...conversation,
          title: newName,
          description: newName,
          updatedAt: new Date(),
        });
      }

      closeEditModal();
      await fetchConversations(1, 20, false);
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
      await fetchConversations(1, 20, false);
    } catch (error) {
      console.error("Failed to delete chat", error);
    }
  }, [router, chatId, deleteConversation, fetchConversations, confirm]);

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
            isIconOnly={btnChildren ? false : true}
            variant={btnChildren ? "flat" : "light"}
            radius={btnChildren ? "md" : "full"}
            // size={btnChildren ? "md" : "sm"}
            size="sm"
          >
            {btnChildren}
            {logo2 ? (
              <ChevronDown width={25} />
            ) : (
              <DotsVerticalIcon
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
            <div className="flex flex-row items-center justify-between gap-2">
              <Star color="white" width={16} />
              {starred ? "Remove" : "Add"} star
            </div>
          </DropdownItem>
          <DropdownItem key="edit" textValue="Rename" onPress={openEditModal}>
            <div className="flex flex-row items-center justify-between gap-2">
              <PencilRenameIcon color="white" width={16} />
              Rename
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
            <div className="flex flex-row items-center justify-between gap-2">
              <Trash color={dangerStateHovered ? "white" : "red"} width={16} />
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
                if (e.key == "Enter") handleEdit();
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

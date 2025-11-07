"use client";

import { Button } from "@heroui/button";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/dropdown";
import { Input } from "@heroui/input";
import { Kbd } from "@heroui/kbd";
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
import {
  ReactNode,
  SetStateAction,
  useCallback,
  useEffect,
  useState,
} from "react";

import { PencilRenameIcon } from "@/components/shared/icons";
import { chatApi } from "@/features/chat/api/chatApi";
import { useFetchConversations } from "@/features/chat/hooks/useConversationList";
import { useDeleteConversation } from "@/hooks/useDeleteConversation";
import { db } from "@/lib/db/chatDb";

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
  const [dangerStateHovered, setDangerStateHovered] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [newName, setNewName] = useState(chatName);
  const router = useRouter();
  const [modalAction, setModalAction] = useState<"edit" | "delete" | null>(
    null,
  );

  const handleStarToggle = async () => {
    try {
      const newStarredValue = starred === undefined ? true : !starred;
      await chatApi.toggleStarConversation(chatId, newStarredValue);

      const conversation = await db.getConversation(chatId);
      if (conversation) {
        await db.putConversation({
          ...conversation,
          starred: newStarredValue,
          updatedAt: new Date(),
        });
      }

      setIsOpen(false);
      await fetchConversations();
    } catch (error) {
      console.error("Failed to update star", error);
    }
  };

  const closeModal = useCallback(() => {
    setIsOpen(false);
    setModalAction(null);
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

      closeModal();
      await fetchConversations(1, 20, false);
    } catch (error) {
      console.error("Failed to update chat name", error);
    }
  };

  const handleDelete = useCallback(async () => {
    try {
      router.push("/c");
      await deleteConversation(chatId);
      closeModal();
      await fetchConversations(1, 20, false);
    } catch (error) {
      console.error("Failed to delete chat", error);
    }
  }, [router, chatId, deleteConversation, fetchConversations, closeModal]);

  const openModal = (action: "edit" | "delete") => {
    setModalAction(action);
    if (action === "edit") setNewName(chatName); // Reset to current chat name when opening edit modal

    setIsOpen(true);
  };

  // Handle Enter key for delete modal
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Enter" && isOpen && modalAction === "delete") {
        event.preventDefault();
        handleDelete();
      }
    };

    if (isOpen && modalAction === "delete")
      document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen, modalAction, handleDelete]);

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
          <DropdownItem
            key="edit"
            textValue="Rename"
            onPress={() => openModal("edit")}
          >
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
            onPress={() => openModal("delete")}
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
        isOpen={isOpen}
        onOpenChange={closeModal}
      >
        <ModalContent>
          {modalAction === "edit" ? (
            <>
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
                  onChange={(e: {
                    target: { value: SetStateAction<string> };
                  }) => setNewName(e.target.value)}
                  onKeyDown={(e: { key: string }) => {
                    if (e.key == "Enter") handleEdit();
                  }}
                />
              </ModalBody>
              <ModalFooter>
                <Button variant="light" onPress={closeModal}>
                  Cancel
                </Button>
                <Button color="primary" onPress={handleEdit}>
                  Save
                </Button>
              </ModalFooter>
            </>
          ) : (
            <>
              <ModalHeader className="pb-0">
                Are you sure you want to delete this chat?
              </ModalHeader>
              <ModalBody className="py-0">
                <p className="text-danger">This action cannot be undone.</p>
              </ModalBody>
              <ModalFooter>
                <Button variant="light" onPress={closeModal}>
                  Cancel
                </Button>
                <Button
                  color="danger"
                  variant="flat"
                  onPress={handleDelete}
                  endContent={<Kbd keys={["enter"]} />}
                >
                  Delete
                </Button>
              </ModalFooter>
            </>
          )}
        </ModalContent>
      </Modal>
    </>
  );
}

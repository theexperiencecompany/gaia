"use client";

import {
  Button,
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/react";
import { useRouter } from "next/navigation";

import { useLogout } from "@/features/auth/hooks/useLogout";
import { chatApi } from "@/features/chat/api/chatApi";
import { useConversation } from "@/features/chat/hooks/useConversation";
import { useFetchConversations } from "@/features/chat/hooks/useConversationList";
import { db } from "@/lib/db/chatDb";

export type ConfirmAction = "logout" | "clear_chats" | null;
//  | "delete_account"

interface ActionConfig {
  title: string;
  description: string;
  confirmText: string;
  cancelText: string;
  variant?: "default" | "destructive";
  handler: () => Promise<void>;
}

interface ConfirmActionDialogProps {
  action: ConfirmAction;
  onOpenChange: (action: ConfirmAction) => void;
}

export function ConfirmActionDialog({
  action,
  onOpenChange,
}: ConfirmActionDialogProps) {
  const { logout } = useLogout();
  const router = useRouter();
  const fetchConversations = useFetchConversations();
  const { updateConvoMessages } = useConversation();

  const getActionConfig = (): ActionConfig | null => {
    switch (action) {
      case "logout":
        return {
          title: "Confirm Logout",
          description: "Are you sure you want to logout?",
          confirmText: "Logout",
          cancelText: "Cancel",
          variant: "destructive",
          handler: async () => {
            await logout();
          },
        };

      case "clear_chats":
        return {
          title: "Clear All Chats",
          description:
            "Are you sure you want to delete all chats? This action cannot be undone.",
          confirmText: "Delete all chats",
          cancelText: "Cancel",
          variant: "destructive",
          handler: async () => {
            try {
              router.push("/c");
              await chatApi.deleteAllConversations();
              await db.clearAll();
              await fetchConversations(1, 20);
              updateConvoMessages();
            } catch (error) {
              console.error("Error clearing chats:", error);
            }
          },
        };

      // case "delete_account":
      //   return {
      //     title: "Delete Account",
      //     description:
      //       "Are you sure you want to permanently delete your account? This action cannot be undone and all your data will be lost.",
      //     confirmText: "Delete account",
      //     cancelText: "Cancel",
      //     variant: "destructive",
      //     handler: async () => {
      //       // TODO: Implement delete account logic
      //       console.log("Delete account");
      //     },
      //   };

      default:
        return null;
    }
  };

  const config = getActionConfig();

  if (!config) return null;

  const handleConfirm = async () => {
    await config.handler();
    onOpenChange(null);
  };

  const handleOpenChange = (open: boolean) => {
    if (!open) {
      onOpenChange(null);
    }
  };

  return (
    <Modal isOpen={!!action} onOpenChange={handleOpenChange}>
      <ModalContent>
        {(onClose) => (
          <>
            <ModalHeader className="flex flex-col gap-1">
              {config.title}
            </ModalHeader>
            <ModalBody>
              <p className="text-sm text-foreground-400">{config.description}</p>
            </ModalBody>
            <ModalFooter>
              <Button
                variant="flat"
                onPress={onClose}
                className="bg-surface-200 text-foreground-300 hover:bg-surface-700"
              >
                {config.cancelText}
              </Button>
              <Button
                color={config.variant === "destructive" ? "danger" : "primary"}
                onPress={() => {
                  handleConfirm();
                  onClose();
                }}
              >
                {config.confirmText}
              </Button>
            </ModalFooter>
          </>
        )}
      </ModalContent>
    </Modal>
  );
}

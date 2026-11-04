"use client";

import { Button, Modal } from "@heroui/react";
import { useRouter } from "next/navigation";

import { useLogout } from "@/features/auth/hooks/useLogout";
import { chatApi } from "@/features/chat/api/chatApi";
import { db } from "@/lib/db/chatDb";
import { batchSyncConversations } from "@/services/syncService";

export type ConfirmAction = "logout" | "clear_chats" | null;
//  | "delete_account"

interface ConfirmActionConfig {
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

  const getActionConfig = (): ConfirmActionConfig | null => {
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
              // Sync from API to get fresh state after clearing
              await batchSyncConversations();
            } catch (error) {
              console.error("Error clearing chats:", error);
            }
          },
        };

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
      <Modal.Backdrop>
        <Modal.Container>
          <Modal.Dialog>
            <Modal.CloseTrigger aria-label="Close" />
            <Modal.Header className="flex flex-col gap-1">
              {config.title}
            </Modal.Header>
            <Modal.Body>
              <p className="text-sm text-zinc-400">{config.description}</p>
            </Modal.Body>
            <Modal.Footer>
              <Button
                variant="tertiary"
                onPress={() => handleOpenChange(false)}
                className="bg-zinc-800 text-zinc-300 hover:bg-zinc-700"
              >
                {config.cancelText}
              </Button>
              <Button
                onPress={() => {
                  handleConfirm();
                  handleOpenChange(false);
                }}
              >
                {config.confirmText}
              </Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}

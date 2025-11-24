"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import { authApi } from "@/features/auth/api/authApi";
import { useUserActions } from "@/features/auth/hooks/useUser";
import { chatApi } from "@/features/chat/api/chatApi";
import { useConversation } from "@/features/chat/hooks/useConversation";
import { useFetchConversations } from "@/features/chat/hooks/useConversationList";
import { useConfirmation } from "@/hooks/useConfirmation";
import { db } from "@/lib/db/chatDb";

import { ModalAction } from "./SettingsMenu";

interface LogoutModalProps {
  modalAction: ModalAction | null;
  setModalAction: (action: ModalAction | null) => void;
}

export default function LogoutModal({
  modalAction,
  setModalAction,
}: LogoutModalProps) {
  const { clearUser } = useUserActions();
  const router = useRouter();
  const fetchConversations = useFetchConversations();
  const { updateConvoMessages } = useConversation();
  const { confirm, confirmationProps } = useConfirmation();

  // Confirm logout action.
  const handleConfirmLogout = async () => {
    try {
      await authApi.logout();
      clearUser();
    } catch (error) {
      console.error("Error during logout:", error);
    } finally {
      router.push("/");
    }
  };

  // Confirm clear chats action.
  const handleConfirmClearChats = async () => {
    try {
      router.push("/c");

      await chatApi.deleteAllConversations();

      // Clear all conversations from IndexedDB
      await db.clearAll();

      // Then fetch from the API to ensure sync with server
      await fetchConversations(1, 20);

      updateConvoMessages();
      // Toast is already shown by the API service
    } catch (error) {
      // Error toast is already shown by the API service
      console.error("Error clearing chats:", error);
    }
  };

  // Trigger confirmation dialog when modalAction changes
  useEffect(() => {
    if (modalAction === "logout") {
      confirm({
        title: "Confirm Logout",
        message: "Are you sure you want to logout?",
        confirmText: "Logout",
        cancelText: "Cancel",
        variant: "destructive",
      }).then((confirmed) => {
        setModalAction(null);
        if (confirmed) {
          handleConfirmLogout();
        }
      });
    } else if (modalAction === "clear_chats") {
      confirm({
        title: "Clear All Chats",
        message: "Are you sure you want to delete all chats?",
        confirmText: "Delete all chats",
        cancelText: "Cancel",
        variant: "destructive",
      }).then((confirmed) => {
        setModalAction(null);
        if (confirmed) {
          handleConfirmClearChats();
        }
      });
    }
  }, [modalAction]);

  return <ConfirmationDialog {...confirmationProps} />;
}

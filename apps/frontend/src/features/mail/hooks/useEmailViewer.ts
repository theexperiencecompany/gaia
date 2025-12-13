import { useState } from "react";
import { toast } from "sonner";

import { mailApi } from "@/features/mail/api/mailApi";
import type { EmailData } from "@/types/features/mailTypes";

import { useEmailReadStatus } from "./useEmailReadStatus";
import { useUrlEmailSelection } from "./useUrlEmailSelection";

/**
 * Hook for managing the currently selected/viewed email
 */
export const useEmailViewer = () => {
  const [threadMessages, setThreadMessages] = useState<EmailData[]>([]);
  const [isLoadingThread, setIsLoadingThread] = useState<boolean>(false);
  const { markAsRead } = useEmailReadStatus();
  const { selectedEmailId, selectEmail, clearSelection } =
    useUrlEmailSelection();

  // Fetch all messages in the email thread
  const fetchEmailThread = async (threadId: string) => {
    if (!threadId) return;

    setIsLoadingThread(true);
    try {
      const response = await mailApi.fetchEmailThread(threadId);
      setThreadMessages(response.thread.messages || []);
    } catch (error) {
      console.error("Error fetching email thread:", error);
      toast.error("Could not load the complete email thread");
      setThreadMessages([]);
    } finally {
      setIsLoadingThread(false);
    }
  };

  // Open email and mark as read if it's unread
  const openEmail = async (email: EmailData) => {
    selectEmail(email.id); // Update URL
    setThreadMessages([]);

    if (email.labelIds?.includes("UNREAD")) {
      await markAsRead(email.id);
    }

    // If this email has a threadId, fetch all messages in the thread
    if (email.threadId) {
      await fetchEmailThread(email.threadId);
    }
  };

  // Close the email detail view
  const closeEmail = () => {
    clearSelection(); // Update URL
    setThreadMessages([]);
  };

  return {
    threadMessages,
    isLoadingThread,
    openEmail,
    closeEmail,
    selectedEmailId, // Expose for URL-based opening
  };
};

import { useRef, useState } from "react";
import { toast } from "sonner";

import { mailApi } from "@/features/mail/api/mailApi";
import type { EmailData } from "@/types/features/mailTypes";

import { useEmailReadStatus } from "./useEmailReadStatus";
import { useUrlEmailSelection } from "./useUrlEmailSelection";

export const useEmailViewer = () => {
  const [threadMessages, setThreadMessages] = useState<EmailData[]>([]);
  const [isLoadingThread, setIsLoadingThread] = useState<boolean>(false);
  const { markAsRead } = useEmailReadStatus();
  const { selectedEmailId, selectEmail, clearSelection } =
    useUrlEmailSelection();
  const abortControllerRef = useRef<AbortController | null>(null);

  const fetchEmailThread = async (threadId: string) => {
    if (!threadId) return;

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    abortControllerRef.current = new AbortController();

    setIsLoadingThread(true);
    try {
      const response = await mailApi.fetchEmailThread(threadId);
      if (!abortControllerRef.current?.signal.aborted) {
        setThreadMessages(response.thread.messages || []);
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      console.error("Error fetching email thread:", error);
      toast.error("Could not load the complete email thread");
      setThreadMessages([]);
    } finally {
      if (!abortControllerRef.current?.signal.aborted) {
        setIsLoadingThread(false);
      }
    }
  };

  const openEmail = async (email: EmailData) => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    selectEmail(email.id);
    setThreadMessages([]);

    if (email.labelIds?.includes("UNREAD")) {
      await markAsRead(email.id);
    }

    if (email.threadId) {
      await fetchEmailThread(email.threadId);
    }
  };

  const closeEmail = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    clearSelection();
    setThreadMessages([]);
  };

  return {
    threadMessages,
    isLoadingThread,
    openEmail,
    closeEmail,
    selectedEmailId,
  };
};

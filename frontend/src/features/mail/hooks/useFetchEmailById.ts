import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { mailApi } from "@/features/mail/api/mailApi";
import type { EmailData } from "@/types/features/mailTypes";

import { useInfiniteEmails } from "./useInfiniteEmails";

/**
 * Hook for managing the currently selected/viewed email
 */
export const useFetchEmailById = (messageId: string | null) => {
  const [mail, setMail] = useState<EmailData | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);

  const { emails } = useInfiniteEmails();

  // Fetch email by ID - wrapped in useCallback to prevent infinite loops
  const fetchEmailById = useCallback(async () => {
    if (!messageId) return;

    // Check if the email is already loaded
    const existingEmail = emails.find((email) => email.id === messageId);
    if (existingEmail) {
      setMail(existingEmail);
      return;
    }

    setIsLoading(true);
    try {
      const response = await mailApi.fetchEmailById(messageId);
      setMail(response);
    } catch (error) {
      console.error("Error fetching email:", error);
      toast.error("Could not load the email");
      setMail(null);
    } finally {
      setIsLoading(false);
    }
  }, [messageId, emails]);

  useEffect(() => {
    if (messageId) fetchEmailById();
    else setMail(null); // Clear email if no messageId
  }, [messageId, fetchEmailById]);

  return {
    mail,
    isLoading,
    fetchEmailById,
  };
};

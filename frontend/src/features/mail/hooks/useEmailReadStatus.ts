import { type InfiniteData, useQueryClient } from "@tanstack/react-query";

import type { EmailData, EmailsResponse } from "@/types/features/mailTypes";

import { mailApi } from "../api/mailApi";

/**
 * Hook for managing email read status with optimistic updates
 * Provides functions to mark emails as read or unread
 */
export const useEmailReadStatus = () => {
  const queryClient = useQueryClient();

  // Update the cache to reflect read status changes immediately
  const updateReadStatus = (emailId: string, isRead: boolean) => {
    queryClient.setQueryData<InfiniteData<EmailsResponse>>(
      ["emails"],
      (oldData) => {
        if (!oldData) return oldData;

        return {
          ...oldData,
          pages: oldData.pages.map((page) => ({
            ...page,
            emails: page.emails.map((email) => {
              if (email.id === emailId) {
                if (isRead) {
                  // Remove UNREAD label
                  return {
                    ...email,
                    labelIds: (email.labelIds || []).filter(
                      (label) => label !== "UNREAD",
                    ),
                  };
                } else {
                  // Add UNREAD label if not already there
                  return {
                    ...email,
                    labelIds: [...(email.labelIds || []), "UNREAD"].filter(
                      (value, index, self) => self.indexOf(value) === index,
                    ),
                  };
                }
              }
              return email;
            }),
          })),
        };
      },
    );
  };

  // Mark email as read with optimistic update
  const markAsRead = async (emailId: string) => {
    // First update UI optimistically
    updateReadStatus(emailId, true);

    try {
      // Then make API call
      await mailApi.markEmailAsRead(emailId, true);
    } catch (error) {
      // If API call fails, revert the optimistic update
      console.error("Error marking email as read:", error);
      updateReadStatus(emailId, false);
    }
  };

  // Mark email as unread with optimistic update
  const markAsUnread = async (emailId: string) => {
    // First update UI optimistically
    updateReadStatus(emailId, false);

    try {
      // Then make API call
      await mailApi.markEmailAsRead(emailId, false);
    } catch (error) {
      // If API call fails, revert the optimistic update
      console.error("Error marking email as unread:", error);
      updateReadStatus(emailId, true);
    }
  };

  // Toggle read/unread status
  const toggleReadStatus = async (email: EmailData) => {
    const isCurrentlyUnread = email.labelIds?.includes("UNREAD");

    if (isCurrentlyUnread) {
      await markAsRead(email.id);
    } else {
      await markAsUnread(email.id);
    }
  };

  return {
    markAsRead,
    markAsUnread,
    toggleReadStatus,
  };
};

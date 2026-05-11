import { type InfiniteData, useQueryClient } from "@tanstack/react-query";

import type { EmailData, EmailsResponse } from "@/types/features/mailTypes";

import { mailApi } from "../api/mailApi";

/**
 * Hook for managing email actions (star, archive, trash) with optimistic updates
 * Provides functions to star/unstar, archive, and trash/untrash emails
 */
export const useEmailActions = () => {
  const queryClient = useQueryClient();

  // Update the cache to reflect starred status changes immediately
  const updateStarredStatus = (emailId: string, isStarred: boolean) => {
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
                if (isStarred) {
                  // Add STARRED label if not already there
                  return {
                    ...email,
                    labelIds: [...(email.labelIds || []), "STARRED"].filter(
                      (value, index, self) => self.indexOf(value) === index,
                    ),
                  };
                } else {
                  // Remove STARRED label
                  return {
                    ...email,
                    labelIds: (email.labelIds || []).filter(
                      (label) => label !== "STARRED",
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

  // Star email with optimistic update
  const starEmail = async (emailId: string) => {
    // First update UI optimistically
    updateStarredStatus(emailId, true);
    try {
      // Then make API call
      await mailApi.toggleStarEmail(emailId, true);
    } catch (error) {
      // If API call fails, revert the optimistic update
      console.error("Error starring email:", error);
      updateStarredStatus(emailId, false);
    }
  };

  // Unstar email with optimistic update
  const unstarEmail = async (emailId: string) => {
    // First update UI optimistically
    updateStarredStatus(emailId, false);
    try {
      // Then make API call
      await mailApi.toggleStarEmail(emailId, false);
    } catch (error) {
      // If API call fails, revert the optimistic update
      console.error("Error unstarring email:", error);
      updateStarredStatus(emailId, true);
    }
  };

  // Toggle star status
  const toggleStarStatus = async (email: EmailData) => {
    const isCurrentlyStarred = email.labelIds?.includes("STARRED");
    if (isCurrentlyStarred) {
      await unstarEmail(email.id);
    } else {
      await starEmail(email.id);
    }
  };

  // Remove email from UI after archiving
  const removeEmailFromList = (emailId: string) => {
    queryClient.setQueryData<InfiniteData<EmailsResponse>>(
      ["emails"],
      (oldData) => {
        if (!oldData) return oldData;
        return {
          ...oldData,
          pages: oldData.pages.map((page) => ({
            ...page,
            emails: page.emails.filter((email) => email.id !== emailId),
          })),
        };
      },
    );
  };

  // Archive email
  const archiveEmail = async (emailId: string) => {
    // First update UI optimistically
    removeEmailFromList(emailId);
    try {
      // Then make API call
      await mailApi.archiveEmail(emailId);
    } catch (error) {
      console.error("Error archiving email:", error);
      // Refresh data since we can't easily revert the removal
      queryClient.invalidateQueries({ queryKey: ["emails"] });
    }
  };

  // Trash email
  const trashEmail = async (emailId: string) => {
    // First update UI optimistically
    removeEmailFromList(emailId);
    try {
      // Then make API call
      await mailApi.trashEmail(emailId);
    } catch (error) {
      console.error("Error moving email to trash:", error);
      // Refresh data since we can't easily revert the removal
      queryClient.invalidateQueries({ queryKey: ["emails"] });
    }
  };

  // Untrash email (restore from trash)
  const untrashEmail = async (emailId: string) => {
    try {
      await mailApi.untrashEmail(emailId);
      // Refresh data to show the restored email
      queryClient.invalidateQueries({ queryKey: ["emails"] });
    } catch (error) {
      console.error("Error restoring email from trash:", error);
    }
  };

  return {
    starEmail,
    unstarEmail,
    toggleStarStatus,
    archiveEmail,
    trashEmail,
    untrashEmail,
  };
};

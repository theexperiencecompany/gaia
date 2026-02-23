import { type InfiniteData, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "@/lib/toast";

import type { EmailsResponse } from "@/types/features/mailTypes";

import { mailApi } from "../api/mailApi";

/**
 * Hook for managing email multi-selection and bulk actions
 */
export const useEmailSelection = () => {
  const [selectedEmails, setSelectedEmails] = useState<Set<string>>(new Set());
  const queryClient = useQueryClient();

  // Toggle email selection
  const toggleEmailSelection = (e: React.MouseEvent, emailId: string) => {
    e.stopPropagation(); // Prevent opening the email

    setSelectedEmails((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(emailId)) {
        newSet.delete(emailId);
      } else {
        newSet.add(emailId);
      }
      return newSet;
    });
  };

  // Clear all selections
  const clearSelections = () => {
    setSelectedEmails(new Set());
  };

  // Bulk actions for selected emails
  const bulkMarkAsRead = async () => {
    if (selectedEmails.size === 0) return;

    // First update UI optimistically
    queryClient.setQueryData<InfiniteData<EmailsResponse>>(
      ["emails"],
      (oldData) => {
        if (!oldData) return oldData;

        return {
          ...oldData,
          pages: oldData.pages.map((page) => ({
            ...page,
            emails: page.emails.map((email) => {
              if (selectedEmails.has(email.id)) {
                return {
                  ...email,
                  labelIds: (email.labelIds || []).filter(
                    (label) => label !== "UNREAD",
                  ),
                };
              }
              return email;
            }),
          })),
        };
      },
    );

    // Show immediate success toast
    toast.success(`${selectedEmails.size} emails marked as read`);

    // Clear selections immediately for better UX
    clearSelections();

    // Then make API call in the background
    try {
      await mailApi.bulkMarkAsRead(Array.from(selectedEmails));
    } catch (error) {
      console.error("Failed to mark emails as read:", error);
      // Refresh data since we may have incomplete state
      queryClient.invalidateQueries({ queryKey: ["emails"] });
    }
  };

  const bulkMarkAsUnread = async () => {
    if (selectedEmails.size === 0) return;

    // First update UI optimistically
    queryClient.setQueryData<InfiniteData<EmailsResponse>>(
      ["emails"],
      (oldData) => {
        if (!oldData) return oldData;

        return {
          ...oldData,
          pages: oldData.pages.map((page) => ({
            ...page,
            emails: page.emails.map((email) => {
              if (selectedEmails.has(email.id)) {
                const newLabelIds = [...(email.labelIds || [])];
                if (!newLabelIds.includes("UNREAD")) {
                  newLabelIds.push("UNREAD");
                }
                return {
                  ...email,
                  labelIds: newLabelIds,
                };
              }
              return email;
            }),
          })),
        };
      },
    );

    // Show immediate success toast
    toast.success(`${selectedEmails.size} emails marked as unread`);

    // Clear selections immediately for better UX
    clearSelections();

    // Then make API call in the background
    try {
      await mailApi.bulkMarkAsUnread(Array.from(selectedEmails));
    } catch (error) {
      console.error("Failed to mark emails as unread:", error);
      // Refresh data since we may have incomplete state
      queryClient.invalidateQueries({ queryKey: ["emails"] });
    }
  };

  const bulkStarEmails = async () => {
    if (selectedEmails.size === 0) return;

    // First update UI optimistically
    queryClient.setQueryData<InfiniteData<EmailsResponse>>(
      ["emails"],
      (oldData) => {
        if (!oldData) return oldData;

        return {
          ...oldData,
          pages: oldData.pages.map((page) => ({
            ...page,
            emails: page.emails.map((email) => {
              if (selectedEmails.has(email.id)) {
                const newLabelIds = [...(email.labelIds || [])];
                if (!newLabelIds.includes("STARRED")) {
                  newLabelIds.push("STARRED");
                }
                return {
                  ...email,
                  labelIds: newLabelIds,
                };
              }
              return email;
            }),
          })),
        };
      },
    );

    // Show immediate success toast
    toast.success(`${selectedEmails.size} emails starred`);

    // Clear selections immediately for better UX
    clearSelections();

    // Then make API call in the background
    try {
      await mailApi.bulkStarEmails(Array.from(selectedEmails));
    } catch (error) {
      console.error("Failed to star emails:", error);
      // Refresh data since we may have incomplete state
      queryClient.invalidateQueries({ queryKey: ["emails"] });
    }
  };

  const bulkUnstarEmails = async () => {
    if (selectedEmails.size === 0) return;

    // First update UI optimistically
    queryClient.setQueryData<InfiniteData<EmailsResponse>>(
      ["emails"],
      (oldData) => {
        if (!oldData) return oldData;

        return {
          ...oldData,
          pages: oldData.pages.map((page) => ({
            ...page,
            emails: page.emails.map((email) => {
              if (selectedEmails.has(email.id)) {
                return {
                  ...email,
                  labelIds: (email.labelIds || []).filter(
                    (label) => label !== "STARRED",
                  ),
                };
              }
              return email;
            }),
          })),
        };
      },
    );

    // Show immediate success toast
    toast.success(`${selectedEmails.size} emails unstarred`);

    // Clear selections immediately for better UX
    clearSelections();

    // Then make API call in the background
    try {
      await mailApi.bulkUnstarEmails(Array.from(selectedEmails));
    } catch (error) {
      console.error("Failed to unstar emails:", error);
      // Refresh data since we may have incomplete state
      queryClient.invalidateQueries({ queryKey: ["emails"] });
    }
  };

  const bulkArchiveEmails = async () => {
    if (selectedEmails.size === 0) return;

    // Store selected email IDs in a local variable before clearing the selection
    const emailIdsToArchive = Array.from(selectedEmails);

    // First update UI optimistically
    queryClient.setQueryData<InfiniteData<EmailsResponse>>(
      ["emails"],
      (oldData) => {
        if (!oldData) return oldData;

        return {
          ...oldData,
          pages: oldData.pages.map((page) => ({
            ...page,
            emails: page.emails.filter(
              (email) => !selectedEmails.has(email.id),
            ),
          })),
        };
      },
    );

    // Show immediate success toast
    toast.success(`${selectedEmails.size} emails archived`);

    // Clear selections immediately for better UX
    clearSelections();

    // Then make API call in the background
    try {
      await mailApi.bulkArchiveEmails(emailIdsToArchive);
    } catch (error) {
      console.error("Failed to archive emails:", error);
      // Refresh data since we may have incomplete state
      queryClient.invalidateQueries({ queryKey: ["emails"] });
    }
  };

  const bulkTrashEmails = async () => {
    if (selectedEmails.size === 0) return;

    // Store selected email IDs in a local variable before clearing the selection
    const emailIdsToTrash = Array.from(selectedEmails);

    // First update UI optimistically
    queryClient.setQueryData<InfiniteData<EmailsResponse>>(
      ["emails"],
      (oldData) => {
        if (!oldData) return oldData;

        return {
          ...oldData,
          pages: oldData.pages.map((page) => ({
            ...page,
            emails: page.emails.filter(
              (email) => !selectedEmails.has(email.id),
            ),
          })),
        };
      },
    );

    // Show immediate success toast
    toast.success(`${selectedEmails.size} emails moved to trash`);

    // Clear selections immediately for better UX
    clearSelections();

    // Then make API call in the background
    try {
      await mailApi.bulkTrashEmails(emailIdsToTrash);
    } catch (error) {
      console.error("Failed to trash emails:", error);
      // Refresh data since we may have incomplete state
      queryClient.invalidateQueries({ queryKey: ["emails"] });
    }
  };

  return {
    selectedEmails,
    toggleEmailSelection,
    clearSelections,
    bulkMarkAsRead,
    bulkMarkAsUnread,
    bulkStarEmails,
    bulkUnstarEmails,
    bulkArchiveEmails,
    bulkTrashEmails,
  };
};

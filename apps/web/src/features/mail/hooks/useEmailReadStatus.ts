import { type InfiniteData, useQueryClient } from "@tanstack/react-query";

import type {
  EmailData,
  EmailsResponse,
  MailTab,
} from "@/types/features/mailTypes";

import { mailApi } from "../api/mailApi";

export const useEmailReadStatus = (tab: MailTab = "inbox") => {
  const queryClient = useQueryClient();
  const queryKey = ["emails", tab];

  const updateReadStatus = (emailId: string, isRead: boolean) => {
    queryClient.setQueryData<InfiniteData<EmailsResponse>>(
      queryKey,
      (oldData) => {
        if (!oldData) return oldData;
        return {
          ...oldData,
          pages: oldData.pages.map((page) => ({
            ...page,
            emails: page.emails.map((email) => {
              if (email.id === emailId) {
                if (isRead) {
                  return {
                    ...email,
                    labelIds: (email.labelIds || []).filter(
                      (label) => label !== "UNREAD",
                    ),
                  };
                }
                return {
                  ...email,
                  labelIds: [
                    ...new Set([...(email.labelIds || []), "UNREAD"]),
                  ],
                };
              }
              return email;
            }),
          })),
        };
      },
    );
  };

  const markAsRead = async (emailId: string) => {
    updateReadStatus(emailId, true);
    try {
      await mailApi.markEmailAsRead(emailId, true);
    } catch (error) {
      console.error("Error marking email as read:", error);
      updateReadStatus(emailId, false);
    }
  };

  const markAsUnread = async (emailId: string) => {
    updateReadStatus(emailId, false);
    try {
      await mailApi.markEmailAsRead(emailId, false);
    } catch (error) {
      console.error("Error marking email as unread:", error);
      updateReadStatus(emailId, true);
    }
  };

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

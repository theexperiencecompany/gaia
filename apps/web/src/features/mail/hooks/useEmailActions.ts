import { type InfiniteData, useQueryClient } from "@tanstack/react-query";

import type {
  EmailData,
  EmailsResponse,
  MailTab,
} from "@/types/features/mailTypes";

import { mailApi } from "../api/mailApi";

export const useEmailActions = (tab: MailTab = "inbox") => {
  const queryClient = useQueryClient();
  const queryKey = ["emails", tab];

  const updateStarredStatus = (emailId: string, isStarred: boolean) => {
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
                if (isStarred) {
                  return {
                    ...email,
                    labelIds: [...(email.labelIds || []), "STARRED"].filter(
                      (value, index, self) => self.indexOf(value) === index,
                    ),
                  };
                }
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
  };

  const starEmail = async (emailId: string) => {
    updateStarredStatus(emailId, true);
    try {
      await mailApi.toggleStarEmail(emailId, true);
    } catch (error) {
      console.error("Error starring email:", error);
      updateStarredStatus(emailId, false);
    }
  };

  const unstarEmail = async (emailId: string) => {
    updateStarredStatus(emailId, false);
    try {
      await mailApi.toggleStarEmail(emailId, false);
    } catch (error) {
      console.error("Error unstarring email:", error);
      updateStarredStatus(emailId, true);
    }
  };

  const toggleStarStatus = async (email: EmailData) => {
    const isCurrentlyStarred = email.labelIds?.includes("STARRED");
    if (isCurrentlyStarred) {
      await unstarEmail(email.id);
    } else {
      await starEmail(email.id);
    }
  };

  const removeEmailFromList = (emailId: string) => {
    queryClient.setQueryData<InfiniteData<EmailsResponse>>(
      queryKey,
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

  const archiveEmail = async (emailId: string) => {
    removeEmailFromList(emailId);
    try {
      await mailApi.archiveEmail(emailId);
    } catch (error) {
      console.error("Error archiving email:", error);
      queryClient.invalidateQueries({ queryKey });
    }
  };

  const trashEmail = async (emailId: string) => {
    removeEmailFromList(emailId);
    try {
      await mailApi.trashEmail(emailId);
    } catch (error) {
      console.error("Error moving email to trash:", error);
      queryClient.invalidateQueries({ queryKey });
    }
  };

  const untrashEmail = async (emailId: string) => {
    try {
      await mailApi.untrashEmail(emailId);
      queryClient.invalidateQueries({ queryKey });
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

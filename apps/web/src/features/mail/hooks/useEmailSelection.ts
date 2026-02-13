import { type InfiniteData, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { toast } from "sonner";

import type { EmailsResponse, MailTab } from "@/types/features/mailTypes";

import { mailApi } from "../api/mailApi";

type Selection = Set<string> | "all";

export const useEmailSelection = (tab: MailTab = "inbox") => {
  const [selectedKeys, setSelectedKeys] = useState<Selection>(
    new Set<string>(),
  );
  const queryClient = useQueryClient();
  const queryKey = ["emails", tab];

  const clearSelections = useCallback(() => {
    setSelectedKeys(new Set<string>());
  }, []);

  const onSelectionChange = useCallback((keys: Selection) => {
    setSelectedKeys(keys);
  }, []);

  const getSelectedIds = useCallback((): string[] => {
    if (selectedKeys === "all") return [];
    return Array.from(selectedKeys);
  }, [selectedKeys]);

  const selectedCount = selectedKeys === "all" ? 0 : selectedKeys.size;

  const bulkMarkAsRead = async () => {
    const ids = getSelectedIds();
    if (ids.length === 0) return;

    queryClient.setQueryData<InfiniteData<EmailsResponse>>(
      queryKey,
      (oldData) => {
        if (!oldData) return oldData;
        return {
          ...oldData,
          pages: oldData.pages.map((page) => ({
            ...page,
            emails: page.emails.map((email) => {
              if (ids.includes(email.id)) {
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

    toast.success(`${ids.length} emails marked as read`);
    clearSelections();

    try {
      await mailApi.bulkMarkAsRead(ids);
    } catch (error) {
      console.error("Failed to mark emails as read:", error);
      queryClient.invalidateQueries({ queryKey });
    }
  };

  const bulkMarkAsUnread = async () => {
    const ids = getSelectedIds();
    if (ids.length === 0) return;

    queryClient.setQueryData<InfiniteData<EmailsResponse>>(
      queryKey,
      (oldData) => {
        if (!oldData) return oldData;
        return {
          ...oldData,
          pages: oldData.pages.map((page) => ({
            ...page,
            emails: page.emails.map((email) => {
              if (ids.includes(email.id)) {
                const newLabelIds = [...(email.labelIds || [])];
                if (!newLabelIds.includes("UNREAD")) {
                  newLabelIds.push("UNREAD");
                }
                return { ...email, labelIds: newLabelIds };
              }
              return email;
            }),
          })),
        };
      },
    );

    toast.success(`${ids.length} emails marked as unread`);
    clearSelections();

    try {
      await mailApi.bulkMarkAsUnread(ids);
    } catch (error) {
      console.error("Failed to mark emails as unread:", error);
      queryClient.invalidateQueries({ queryKey });
    }
  };

  const bulkStarEmails = async () => {
    const ids = getSelectedIds();
    if (ids.length === 0) return;

    queryClient.setQueryData<InfiniteData<EmailsResponse>>(
      queryKey,
      (oldData) => {
        if (!oldData) return oldData;
        return {
          ...oldData,
          pages: oldData.pages.map((page) => ({
            ...page,
            emails: page.emails.map((email) => {
              if (ids.includes(email.id)) {
                const newLabelIds = [...(email.labelIds || [])];
                if (!newLabelIds.includes("STARRED")) {
                  newLabelIds.push("STARRED");
                }
                return { ...email, labelIds: newLabelIds };
              }
              return email;
            }),
          })),
        };
      },
    );

    toast.success(`${ids.length} emails starred`);
    clearSelections();

    try {
      await mailApi.bulkStarEmails(ids);
    } catch (error) {
      console.error("Failed to star emails:", error);
      queryClient.invalidateQueries({ queryKey });
    }
  };

  const bulkArchiveEmails = async () => {
    const ids = getSelectedIds();
    if (ids.length === 0) return;

    queryClient.setQueryData<InfiniteData<EmailsResponse>>(
      queryKey,
      (oldData) => {
        if (!oldData) return oldData;
        return {
          ...oldData,
          pages: oldData.pages.map((page) => ({
            ...page,
            emails: page.emails.filter((email) => !ids.includes(email.id)),
          })),
        };
      },
    );

    toast.success(`${ids.length} emails archived`);
    clearSelections();

    try {
      await mailApi.bulkArchiveEmails(ids);
    } catch (error) {
      console.error("Failed to archive emails:", error);
      queryClient.invalidateQueries({ queryKey });
    }
  };

  const bulkTrashEmails = async () => {
    const ids = getSelectedIds();
    if (ids.length === 0) return;

    queryClient.setQueryData<InfiniteData<EmailsResponse>>(
      queryKey,
      (oldData) => {
        if (!oldData) return oldData;
        return {
          ...oldData,
          pages: oldData.pages.map((page) => ({
            ...page,
            emails: page.emails.filter((email) => !ids.includes(email.id)),
          })),
        };
      },
    );

    toast.success(`${ids.length} emails moved to trash`);
    clearSelections();

    try {
      await mailApi.bulkTrashEmails(ids);
    } catch (error) {
      console.error("Failed to trash emails:", error);
      queryClient.invalidateQueries({ queryKey });
    }
  };

  return {
    selectedKeys,
    selectedCount,
    onSelectionChange,
    clearSelections,
    bulkMarkAsRead,
    bulkMarkAsUnread,
    bulkStarEmails,
    bulkArchiveEmails,
    bulkTrashEmails,
  };
};

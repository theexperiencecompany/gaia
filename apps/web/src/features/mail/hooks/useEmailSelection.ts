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

  const getAllEmailIds = useCallback((): string[] => {
    const data =
      queryClient.getQueryData<InfiniteData<EmailsResponse>>(queryKey);
    if (!data) return [];
    return data.pages.flatMap((page) => page.emails.map((e) => e.id));
  }, [queryClient, queryKey]);

  const getSelectedIds = useCallback((): string[] => {
    if (selectedKeys === "all") return getAllEmailIds();
    return Array.from(selectedKeys);
  }, [selectedKeys, getAllEmailIds]);

  const selectedCount =
    selectedKeys === "all" ? getAllEmailIds().length : selectedKeys.size;

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

    clearSelections();

    try {
      await mailApi.bulkMarkAsRead(ids);
      toast.success(`${ids.length} emails marked as read`);
    } catch (error) {
      console.error("Failed to mark emails as read:", error);
      toast.error("Failed to mark emails as read");
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
                const newLabelIds = [
                  ...new Set([...(email.labelIds || []), "UNREAD"]),
                ];
                return { ...email, labelIds: newLabelIds };
              }
              return email;
            }),
          })),
        };
      },
    );

    clearSelections();

    try {
      await mailApi.bulkMarkAsUnread(ids);
      toast.success(`${ids.length} emails marked as unread`);
    } catch (error) {
      console.error("Failed to mark emails as unread:", error);
      toast.error("Failed to mark emails as unread");
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
                const newLabelIds = [
                  ...new Set([...(email.labelIds || []), "STARRED"]),
                ];
                return { ...email, labelIds: newLabelIds };
              }
              return email;
            }),
          })),
        };
      },
    );

    clearSelections();

    try {
      await mailApi.bulkStarEmails(ids);
      toast.success(`${ids.length} emails starred`);
    } catch (error) {
      console.error("Failed to star emails:", error);
      toast.error("Failed to star emails");
      queryClient.invalidateQueries({ queryKey });
    }
  };

  const bulkUnstarEmails = async () => {
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

    clearSelections();

    try {
      await mailApi.bulkUnstarEmails(ids);
      toast.success(`${ids.length} emails unstarred`);
    } catch (error) {
      console.error("Failed to unstar emails:", error);
      toast.error("Failed to unstar emails");
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

    clearSelections();

    try {
      await mailApi.bulkArchiveEmails(ids);
      toast.success(`${ids.length} emails archived`);
    } catch (error) {
      console.error("Failed to archive emails:", error);
      toast.error("Failed to archive emails");
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

    clearSelections();

    try {
      await mailApi.bulkTrashEmails(ids);
      toast.success(`${ids.length} emails moved to trash`);
    } catch (error) {
      console.error("Failed to trash emails:", error);
      toast.error("Failed to move emails to trash");
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
    bulkUnstarEmails,
    bulkArchiveEmails,
    bulkTrashEmails,
  };
};

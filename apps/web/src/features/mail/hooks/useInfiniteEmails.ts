import { type InfiniteData, useInfiniteQuery } from "@tanstack/react-query";
import { useCallback } from "react";

import { mailApi } from "@/features/mail/api/mailApi";
import type { EmailsResponse, MailTab } from "@/types/features/mailTypes";

export const useInfiniteEmails = (tab: MailTab = "inbox") => {
  const { data, isLoading, fetchNextPage, hasNextPage, error } =
    useInfiniteQuery<
      EmailsResponse,
      Error,
      InfiniteData<EmailsResponse>,
      string[]
    >({
      queryKey: ["emails", tab],
      queryFn: ({ pageParam }) =>
        mailApi.fetchEmailsByTab(tab, pageParam as string | undefined),
      getNextPageParam: (lastPage) => lastPage.nextPageToken || undefined,
      initialPageParam: undefined,
      retry: 0,
      refetchOnWindowFocus: true,
      staleTime: 2 * 60 * 1000,
    });

  const emails = data
    ? data.pages.flatMap((page: EmailsResponse) => page.emails)
    : [];

  const isItemLoaded = useCallback(
    (index: number, itemCount: number) => !hasNextPage || index < itemCount,
    [hasNextPage],
  );

  const loadMoreItems = useCallback(
    async (_startIndex: number, _stopIndex: number) => {
      if (hasNextPage && !error) {
        try {
          await fetchNextPage();
        } catch (fetchError) {
          console.error("Failed to fetch more emails:", fetchError);
        }
      }
    },
    [hasNextPage, fetchNextPage, error],
  );

  return {
    data,
    emails,
    isLoading,
    fetchNextPage,
    hasNextPage,
    isItemLoaded,
    loadMoreItems,
    error,
  };
};

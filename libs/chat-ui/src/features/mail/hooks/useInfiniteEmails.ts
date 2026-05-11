import { type InfiniteData, useInfiniteQuery } from "@tanstack/react-query";
import { useCallback } from "react";

import { fetchEmails } from "@/features/mail/utils/mailUtils";
import type { EmailsResponse } from "@/types/features/mailTypes";

/**
 * Hook for handling infinite loading of emails
 */
export const useInfiniteEmails = () => {
  const { data, isLoading, fetchNextPage, hasNextPage, error } =
    useInfiniteQuery<
      EmailsResponse,
      Error,
      InfiniteData<EmailsResponse>,
      string[]
    >({
      queryKey: ["emails"],
      queryFn: fetchEmails,
      getNextPageParam: (lastPage) => lastPage.nextPageToken || undefined,
      initialPageParam: undefined,
      retry: 0, // Explicitly set to 0 to override global retry settings
      refetchOnWindowFocus: false, // Prevent refetch on window focus
      refetchOnReconnect: false, // Prevent refetch on network reconnect
      refetchOnMount: false, // Prevent refetch on component mount
      staleTime: Infinity, // Keep data fresh to prevent background refetching
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
      // Only attempt to fetch more if we have a next page and no current error
      if (hasNextPage && !error) {
        try {
          await fetchNextPage();
        } catch (fetchError) {
          // Log the error but don't throw it to prevent infinite retry loops
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
    error, // Expose error state so components can handle it
  };
};

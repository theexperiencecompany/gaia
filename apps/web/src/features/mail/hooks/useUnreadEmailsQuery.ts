import { useInfiniteQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/typed";
import { asEmailData } from "@/types/features/mailTypes";

/**
 * React Query infinite query hook for fetching unread emails with scroll-based pagination
 */
export const useUnreadEmailsQuery = (
  maxResults: number = 10,
  options?: { enabled?: boolean },
) => {
  return useInfiniteQuery({
    queryKey: ["unread-emails-infinite", maxResults],
    queryFn: async ({ pageParam }: { pageParam: string | null }) => {
      const page = await api.get("/api/v1/gmail/search", {
        query: {
          is_read: false,
          max_results: maxResults,
          page_token: pageParam ?? undefined,
        },
        errorMessage: "Failed to fetch unread emails",
        silent: true,
      });
      return {
        messages: asEmailData(page.messages),
        nextPageToken: page.nextPageToken,
      };
    },
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.nextPageToken ?? null,
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 10 * 60 * 1000, // 10 minutes
    retry: 2,
    refetchOnWindowFocus: false,
    ...options,
  });
};

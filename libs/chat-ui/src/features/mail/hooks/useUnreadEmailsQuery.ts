import { useInfiniteQuery } from "@tanstack/react-query";

import { apiService } from "@/lib/api/service";
import type { EmailData } from "@/types/features/mailTypes";

interface UnreadEmailsResponse {
  messages: EmailData[];
  nextPageToken?: string;
}

/**
 * React Query infinite query hook for fetching unread emails with scroll-based pagination
 */
export const useUnreadEmailsQuery = (
  maxResults: number = 10,
  options?: { enabled?: boolean },
) => {
  return useInfiniteQuery({
    queryKey: ["unread-emails-infinite", maxResults],
    queryFn: async ({
      pageParam,
    }: {
      pageParam: string | null;
    }): Promise<UnreadEmailsResponse> => {
      const params = new URLSearchParams({
        is_read: "false",
        max_results: String(maxResults),
      });
      if (pageParam) {
        params.set("page_token", pageParam);
      }
      const response = await apiService.get<UnreadEmailsResponse>(
        `/gmail/search?${params.toString()}`,
        {
          errorMessage: "Failed to fetch unread emails",
          silent: true,
        },
      );
      return response;
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

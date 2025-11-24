import { type UseQueryOptions, useQuery } from "@tanstack/react-query";

import { apiService } from "@/lib/api";
import type { EmailData } from "@/types/features/mailTypes";

interface UnreadEmailsResponse {
  messages: EmailData[];
  nextPageToken?: string;
}

/**
 * React Query hook for fetching unread emails with 5-minute caching
 */
export const useUnreadEmailsQuery = (
  maxResults: number = 10,
  options?: Partial<UseQueryOptions<EmailData[], Error>>,
) => {
  return useQuery({
    queryKey: ["unread-emails", maxResults],
    queryFn: async (): Promise<EmailData[]> => {
      const response = await apiService.get<UnreadEmailsResponse>(
        `/gmail/search?is_read=false&max_results=${maxResults}`,
        {
          errorMessage: "Failed to fetch unread emails",
          silent: true,
        },
      );
      return response.messages || [];
    },
    staleTime: 5 * 60 * 1000, // 5 minutes - data stays fresh
    gcTime: 10 * 60 * 1000, // 10 minutes - cache persistence
    retry: 2,
    refetchOnWindowFocus: false, // Don't refetch on window focus for dashboard
    ...options,
  });
};

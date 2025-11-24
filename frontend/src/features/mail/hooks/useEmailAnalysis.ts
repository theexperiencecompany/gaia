import { useQuery, useQueryClient } from "@tanstack/react-query";

import { mailApi } from "@/features/mail/api/mailApi";
import type { EmailImportanceSummary } from "@/types/features/mailTypes";

/**
 * Hook to fetch email importance summary/analysis for a specific email
 * This will first check if the data is available in the bulk query cache
 * @param emailId - The email message ID
 * @param enabled - Whether the query should be enabled
 * @returns Query result with email analysis data
 */
export function useEmailSummary(emailId: string, enabled: boolean = true) {
  return useQuery({
    queryKey: ["email-summary", emailId],
    queryFn: async () => {
      if (!emailId) {
        throw new Error("Email ID is required");
      }

      // If not found in cache, fetch individually
      return await mailApi.fetchEmailSummaryById(emailId);
    },
    enabled: enabled && !!emailId,
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 10 * 60 * 1000, // 10 minutes (was cacheTime)
    retry: (failureCount, error) => {
      // Don't retry on 404 errors (email not found)
      if (error instanceof Error && error.message.includes("404")) {
        return false;
      }
      // Retry up to 2 times for other errors
      return failureCount < 2;
    },
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30000),
  });
}

/**
 * Hook to fetch multiple email importance summaries
 * @param limit - Number of emails to fetch
 * @param importantOnly - Whether to fetch only important emails
 * @param enabled - Whether the query should be enabled
 * @returns Query result with email summaries data
 */
export function useEmailSummaries(
  limit: number = 50,
  importantOnly: boolean = false,
  enabled: boolean = true,
) {
  return useQuery({
    queryKey: ["email-summaries", limit, importantOnly],
    queryFn: async () => {
      return await mailApi.fetchEmailSummaries(limit, importantOnly);
    },
    enabled,
    staleTime: 2 * 60 * 1000, // 2 minutes
    gcTime: 5 * 60 * 1000, // 5 minutes (was cacheTime)
    retry: 2,
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30000),
  });
}

/**
 * Hook to fetch email importance summaries for multiple emails in bulk
 * @param messageIds - Array of email message IDs
 * @param enabled - Whether the query should be enabled
 * @returns Query result with bulk email summaries data
 */
export function useBulkEmailSummaries(
  messageIds: string[],
  enabled: boolean = true,
) {
  return useQuery({
    queryKey: ["bulk-email-summaries", messageIds],
    queryFn: async () => {
      if (!messageIds || messageIds.length === 0) {
        return {
          status: "success",
          emails: {},
          found_count: 0,
          missing_count: 0,
          found_message_ids: [],
          missing_message_ids: [],
        };
      }
      return await mailApi.fetchEmailSummaryByIds(messageIds);
    },
    enabled: enabled && messageIds.length > 0,
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 10 * 60 * 1000, // 10 minutes
    retry: 2,
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30000),
  });
}

/**
 * Hook to get email analysis status for multiple emails using bulk API
 * @param emailIds - Array of email IDs to check
 * @param enabled - Whether the query should be enabled
 * @returns Query result with analysis status for each email
 */
export function useEmailAnalysisStatus(
  emailIds: string[],
  enabled: boolean = true,
) {
  const bulkQuery = useBulkEmailSummaries(emailIds, enabled);

  return {
    ...bulkQuery,
    data: bulkQuery.data
      ? emailIds.map((emailId) => ({
          emailId,
          hasAnalysis: !!bulkQuery.data?.emails[emailId],
          analysis: bulkQuery.data?.emails[emailId] || null,
        }))
      : undefined,
  };
}

/**
 * Hook for efficiently checking if emails have AI analysis available
 * This is optimized for use in email lists where you need to show AI indicators
 * @param emailIds - Array of email IDs to check
 * @param enabled - Whether the query should be enabled
 * @returns Object with hasAnalysis function and loading state
 */
export function useEmailAnalysisIndicators(
  emailIds: string[],
  enabled: boolean = true,
) {
  const bulkQuery = useBulkEmailSummaries(emailIds, enabled);

  return {
    hasAnalysis: (emailId: string) => !!bulkQuery.data?.emails[emailId],
    getAnalysis: (emailId: string) => bulkQuery.data?.emails[emailId] || null,
    isLoading: bulkQuery.isLoading,
    error: bulkQuery.error,
    foundCount: bulkQuery.data?.found_count || 0,
    missingCount: bulkQuery.data?.missing_count || 0,
  };
}

/**
 * Hook to prefetch email analysis for better UX
 * @param emailId - The email message ID to prefetch
 */
export function usePrefetchEmailAnalysis() {
  const queryClient = useQueryClient();

  return (emailId: string) => {
    if (!emailId) return;

    queryClient.prefetchQuery({
      queryKey: ["email-summary", emailId],
      queryFn: async () => {
        return await mailApi.fetchEmailSummaryById(emailId);
      },
      staleTime: 5 * 60 * 1000, // 5 minutes
    });
  };
}

/**
 * Hook to invalidate email analysis cache
 */
export function useInvalidateEmailAnalysis() {
  const queryClient = useQueryClient();

  return {
    invalidateEmailSummary: (emailId: string) => {
      queryClient.invalidateQueries({
        queryKey: ["email-summary", emailId],
      });
    },
    invalidateEmailSummaries: () => {
      queryClient.invalidateQueries({
        queryKey: ["email-summaries"],
      });
    },
    invalidateBulkSummaries: (emailIds?: string[]) => {
      if (emailIds) {
        queryClient.invalidateQueries({
          queryKey: ["bulk-email-summaries", emailIds],
        });
      } else {
        queryClient.invalidateQueries({
          queryKey: ["bulk-email-summaries"],
        });
      }
    },
    invalidateAnalysisStatus: (emailIds?: string[]) => {
      if (emailIds) {
        queryClient.invalidateQueries({
          queryKey: ["bulk-email-summaries", emailIds],
        });
      } else {
        queryClient.invalidateQueries({
          queryKey: ["bulk-email-summaries"],
        });
      }
    },
  };
}

// Re-export types for convenience
export type { EmailImportanceSummary };

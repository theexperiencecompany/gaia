"use client";
import { useQuery } from "@tanstack/react-query";

import { mailApi } from "@/features/mail/api/mailApi";
import type { EmailImportanceSummary } from "@/types/features/mailTypes";

export function useHoverSummary(emailId: string, enabled: boolean) {
  return useQuery<EmailImportanceSummary | null>({
    queryKey: ["hover-summary", emailId],
    queryFn: async () => {
      const result = await mailApi.fetchEmailSummaryById(emailId);
      if (result?.email) return result.email;
      return null;
    },
    enabled: enabled && !!emailId,
    staleTime: 10 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
    retry: false,
  });
}

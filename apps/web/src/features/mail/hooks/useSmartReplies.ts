"use client";
import { useQuery } from "@tanstack/react-query";

import { mailApi } from "@/features/mail/api/mailApi";

export function useSmartReplies(messageId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ["smart-replies", messageId],
    queryFn: () => mailApi.generateSmartReplies(messageId!),
    enabled: enabled && !!messageId,
    staleTime: 30 * 60 * 1000,
    gcTime: 60 * 60 * 1000,
    retry: 1,
  });
}

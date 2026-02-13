import { useQuery } from "@tanstack/react-query";

import { mailApi } from "@/features/mail/api/mailApi";
import type { EmailData } from "@/types/features/mailTypes";

export const useFetchEmailById = (messageId: string | null) => {
  const { data: mail = null, isLoading } = useQuery<EmailData | null>({
    queryKey: ["email", messageId],
    queryFn: async () => {
      if (!messageId) return null;
      return mailApi.fetchEmailById(messageId);
    },
    enabled: !!messageId,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  });

  return {
    mail,
    isLoading,
  };
};

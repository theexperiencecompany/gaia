"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { referralsApi } from "../api/referralsApi";

const chatCardKey = (turnId: string) => ["referrals", "chat-card", turnId];

/**
 * Asks the server once per finished turn whether the share card may show; a
 * yes spends the user's weekly referral nudge, so the answer is cached for good.
 */
export function useChatCardNudge(turnId: string, enabled: boolean) {
  const queryClient = useQueryClient();
  const claim = useQuery({
    queryKey: chatCardKey(turnId),
    queryFn: referralsApi.claimChatCard,
    enabled,
    staleTime: Number.POSITIVE_INFINITY,
    gcTime: Number.POSITIVE_INFINITY,
    retry: false,
    refetchOnWindowFocus: false,
  });
  // Hidden straight away and never refetched: a refetch would claim the week again.
  const dismissal = useMutation({
    mutationFn: referralsApi.dismissChatCard,
    onMutate: () => {
      queryClient.setQueryData(chatCardKey(turnId), { show: false });
    },
  });

  return { show: claim.data?.show === true, dismiss: () => dismissal.mutate() };
}

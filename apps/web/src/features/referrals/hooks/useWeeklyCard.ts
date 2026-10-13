"use client";

import type { ReferralWeeklyCardResponse } from "@shared/api/generated";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useIsPaid } from "@/features/pricing/hooks/useIsPaid";
import { referralsApi } from "../api/referralsApi";

const WEEKLY_CARD_KEY = ["referrals", "weekly-card"];

/**
 * The Monday recap card. A shown card spends the user's weekly referral nudge,
 * so the server's answer is asked once and cached for the session.
 */
export function useWeeklyCard() {
  const queryClient = useQueryClient();
  const { isPaid, isUnknown } = useIsPaid();
  const claim = useQuery({
    queryKey: WEEKLY_CARD_KEY,
    queryFn: referralsApi.claimWeeklyCard,
    enabled: !isUnknown && isPaid,
    staleTime: Number.POSITIVE_INFINITY,
    gcTime: Number.POSITIVE_INFINITY,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const dismissal = useMutation({ mutationFn: referralsApi.dismissWeeklyCard });

  const dismiss = () => {
    queryClient.setQueryData<ReferralWeeklyCardResponse>(
      WEEKLY_CARD_KEY,
      (card) => (card ? { ...card, show: false } : card),
    );
    dismissal.mutate();
  };

  const card = claim.data?.show ? claim.data : undefined;
  return { card, dismiss };
}

/** The share image for a week: the card's own numbers, drawn by /api/og/weekly. */
export function weeklyImagePath(card: ReferralWeeklyCardResponse): string {
  const params = new URLSearchParams({
    code: card.code,
    minutes: String(card.stats.minutes_saved),
    actions: String(card.stats.actions),
    runs: String(card.stats.workflow_runs),
  });
  return `/api/og/weekly?${params.toString()}`;
}

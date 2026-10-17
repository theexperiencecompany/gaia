"use client";

import type { ReferralWeeklyCardResponse } from "@shared/api/generated";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { addWeeks, format, startOfISOWeek } from "date-fns";
import { useEffect, useState } from "react";
import { useIsPaid } from "@/features/pricing/hooks/useIsPaid";
import { referralsApi } from "../api/referralsApi";

function localWeekStart(now: Date): string {
  return format(startOfISOWeek(now), "yyyy-MM-dd");
}

/** The current local ISO week, which rolls over at Monday 00:00 even on a page left open. */
function useLocalWeek(): string {
  const [week, setWeek] = useState(() => localWeekStart(new Date()));
  useEffect(() => {
    const nextWeek = addWeeks(startOfISOWeek(new Date()), 1);
    const timer = setTimeout(
      () => setWeek(localWeekStart(new Date())),
      nextWeek.getTime() - Date.now(),
    );
    return () => clearTimeout(timer);
  }, [week]);
  return week;
}

/**
 * The Monday recap card. A shown card spends the user's weekly referral nudge,
 * so the server's answer is asked once per local week and never refetched within it.
 */
export function useWeeklyCard() {
  const queryClient = useQueryClient();
  const { isPaid, isUnknown } = useIsPaid();
  // One claim per local week: a new week is a new key, so last week's answer never carries over.
  const key = ["referrals", "weekly-card", useLocalWeek()];
  const claim = useQuery({
    queryKey: key,
    queryFn: referralsApi.claimWeeklyCard,
    enabled: !isUnknown && isPaid,
    staleTime: Number.POSITIVE_INFINITY,
    retry: false,
    refetchOnWindowFocus: false,
  });
  // Hidden straight away and never refetched: a refetch would claim the week again.
  const dismissal = useMutation({
    mutationFn: referralsApi.dismissWeeklyCard,
    onMutate: () => {
      queryClient.setQueryData<ReferralWeeklyCardResponse>(key, (card) =>
        card ? { ...card, show: false } : card,
      );
    },
  });

  const card = claim.data?.show ? claim.data : undefined;
  return { card, dismiss: () => dismissal.mutate() };
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

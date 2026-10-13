"use client";

import type { ReferralWeeklyCardResponse } from "@shared/api/generated";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useIsPaid } from "@/features/pricing/hooks/useIsPaid";
import { referralsApi } from "../api/referralsApi";

const WEEKLY_CARD_STALE_MS = 60 * 60 * 1000;
/** Holds the window_start of the week the user closed the card for. */
const DISMISSED_WEEK_KEY = "gaia_weekly_card_dismissed_week";

/** The Monday recap card when the server says it is due and the user hasn't closed this week's. */
export function useWeeklyCard() {
  const { isPaid, isUnknown } = useIsPaid();
  const { data } = useQuery({
    queryKey: ["referrals", "weekly-card"],
    queryFn: referralsApi.getWeeklyCard,
    enabled: !isUnknown && isPaid,
    staleTime: WEEKLY_CARD_STALE_MS,
    retry: false,
  });
  // localStorage exists only after mount; until then the card stays hidden.
  const [dismissedWeek, setDismissedWeek] = useState<string | null>(null);
  const [isHydrated, setIsHydrated] = useState(false);
  useEffect(() => {
    setDismissedWeek(localStorage.getItem(DISMISSED_WEEK_KEY));
    setIsHydrated(true);
  }, []);

  const card: ReferralWeeklyCardResponse | undefined =
    isHydrated && data?.show && dismissedWeek !== data.stats.window_start
      ? data
      : undefined;

  const dismiss = () => {
    if (!data) return;
    localStorage.setItem(DISMISSED_WEEK_KEY, data.stats.window_start);
    setDismissedWeek(data.stats.window_start);
  };

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

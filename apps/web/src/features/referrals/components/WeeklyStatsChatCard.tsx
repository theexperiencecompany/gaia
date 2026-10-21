"use client";

import { useWeeklyCard } from "../hooks/useWeeklyCard";
import { WeeklyStatsCard } from "./WeeklyStatsCard";

/** On a new chat, Mondays only, when the server grants this week's referral nudge. */
export function WeeklyStatsChatCard({ className }: { className?: string }) {
  const { card, dismiss } = useWeeklyCard();
  if (!card) return null;
  return (
    <WeeklyStatsCard card={card} onDismiss={dismiss} className={className} />
  );
}

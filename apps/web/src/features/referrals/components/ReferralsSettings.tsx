"use client";

import { Skeleton } from "@heroui/skeleton";
import * as m from "motion/react-m";

import LazyMotionProvider from "@/features/landing/components/LazyMotionProvider";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";

import { useReferralOverview } from "../hooks/useReferrals";
import type { ReferralOverview } from "../types";
import { FriendsList } from "./FriendsList";
import { GoalLadder } from "./GoalLadder";
import { RewardTicket } from "./RewardTicket";
import { ticketCopyForMonths } from "./referralVisuals";
import { ShareZone } from "./ShareZone";
import { StatTiles } from "./StatTiles";

const EASE = [0.19, 1, 0.22, 1] as const;

// A staggered fade-up used for each band of the page on mount.
const reveal = (delay: number) => ({
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.5, ease: EASE, delay },
});

// Uppercase eyebrow shared by every section.
function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="mb-3 text-xs font-medium uppercase tracking-wider text-zinc-500">
      {children}
    </p>
  );
}

function ReferralsContent({ overview }: { overview: ReferralOverview }) {
  const ticket = ticketCopyForMonths(overview.next_goal_reward_months);

  return (
    <SettingsPage>
      {/* Gift hero. */}
      <m.div
        {...reveal(0)}
        className="flex flex-col items-center rounded-3xl bg-zinc-800 p-8 text-center"
      >
        <RewardTicket value={ticket.value} caption={ticket.caption} />
        <h2 className="mt-7 max-w-md font-serif text-3xl font-normal leading-tight tracking-tight text-white">
          Give a friend GAIA PRO. Get a month free.
        </h2>
        <p className="mt-3 max-w-md text-sm leading-relaxed text-zinc-400">
          They get 50% off their first 2 months — a $30 gift. You get 1 month of
          PRO free when they subscribe.
        </p>
      </m.div>

      {/* Share / action zone. */}
      <m.div {...reveal(0.06)}>
        <ShareZone shareLink={overview.share_link} code={overview.code} />
      </m.div>

      {/* Points explainer. */}
      <m.p
        {...reveal(0.1)}
        className="px-1 text-sm leading-relaxed text-zinc-400"
      >
        Every friend who signs up nudges your progress forward. When they
        subscribe, you earn a full month of PRO — free.
      </m.p>

      {/* Goal ladder. */}
      <m.div {...reveal(0.14)}>
        <SectionLabel>Your next free month</SectionLabel>
        <GoalLadder overview={overview} />
      </m.div>

      {/* Stat tiles. */}
      <m.div {...reveal(0.18)}>
        <StatTiles stats={overview.stats} />
      </m.div>

      {/* Friends. */}
      <m.div {...reveal(0.22)}>
        <SectionLabel>Friends you've invited</SectionLabel>
        <FriendsList friends={overview.friends} />
      </m.div>
    </SettingsPage>
  );
}

function ReferralsSkeleton() {
  return (
    <SettingsPage>
      <div className="flex flex-col items-center gap-4 rounded-3xl bg-zinc-800 p-8">
        <Skeleton className="h-28 w-64 rounded-3xl" />
        <Skeleton className="h-7 w-72 rounded-lg" />
        <Skeleton className="h-4 w-80 rounded-lg" />
      </div>
      <Skeleton className="h-14 w-full rounded-2xl" />
      <div className="grid grid-cols-4 gap-2">
        {["a", "b", "c", "d"].map((k) => (
          <Skeleton key={k} className="h-20 rounded-2xl" />
        ))}
      </div>
      <Skeleton className="h-32 w-full rounded-2xl" />
    </SettingsPage>
  );
}

export function ReferralsSettings() {
  const { data: overview, isLoading } = useReferralOverview();

  return (
    <LazyMotionProvider>
      {isLoading || !overview ? (
        <ReferralsSkeleton />
      ) : (
        <ReferralsContent overview={overview} />
      )}
    </LazyMotionProvider>
  );
}

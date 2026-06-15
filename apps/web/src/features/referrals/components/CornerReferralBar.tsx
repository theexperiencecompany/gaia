"use client";

import { Button } from "@heroui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@heroui/popover";
import { Progress } from "@heroui/progress";
import { CancelIcon, GiftIcon } from "@icons";
import { useEffect, useState } from "react";
import { useRouter } from "@/i18n/navigation";
import { useReferralOverview } from "../hooks/useReferrals";
import { ShareZone } from "./ShareZone";

const STORAGE_KEY = "referral-corner-minimized:v1";
const HUB_ROUTE = "/settings/referrals";

/**
 * Persistent bottom-right referral bar (Variant B). A labeled mini-card showing
 * live progress; minimizable to a single gift icon (state remembered). Clicking
 * opens a deliberately simple popover that nudges and hands off to the full hub
 * — no email field, no ladder. Tasteful shine, no glow.
 */
export function CornerReferralBar() {
  const router = useRouter();
  const { data: overview } = useReferralOverview();
  const [minimized, setMinimized] = useState(false);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) setMinimized(JSON.parse(stored));
    } catch {
      // localStorage unavailable — use default
    }
  }, []);

  const persistMinimized = (next: boolean) => {
    setMinimized(next);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      // localStorage unavailable — state still updated in memory
    }
  };

  // Persistent referral home for every logged-in user (free + PRO): free users
  // are invited to earn a free month of PRO by referring. Render nothing until
  // the overview is ready.
  if (!overview) return null;

  const friendsToGo = Math.max(
    1,
    Math.ceil(
      (overview.next_goal_threshold - overview.points) /
        Math.max(1, overview.next_goal_reward_months * 100),
    ),
  );
  const headline =
    overview.points > 0
      ? `${friendsToGo} ${friendsToGo === 1 ? "friend" : "friends"} to your free month`
      : "Invite friends, get a free month of PRO";

  if (minimized) {
    return (
      <div className="animate-scale-in fixed right-6 bottom-6 z-50">
        <Button
          isIconOnly
          radius="full"
          aria-label="Open referrals"
          className="h-11 w-11 bg-zinc-800/60 text-primary backdrop-blur-xl hover:bg-zinc-800"
          onPress={() => persistMinimized(false)}
        >
          <GiftIcon width={20} height={20} />
        </Button>
      </div>
    );
  }

  return (
    <div className="animate-scale-in fixed right-6 bottom-6 z-50">
      <Popover placement="top-end" offset={12} radius="lg">
        <div className="animate-shine relative w-[264px] overflow-hidden rounded-2xl bg-zinc-800/40 p-3 backdrop-blur-xl">
          <div className="mb-2 flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="flex size-6 items-center justify-center rounded-lg bg-primary/15 text-primary">
                <GiftIcon width={15} height={15} />
              </span>
              <span className="text-sm font-medium text-zinc-100">
                {headline}
              </span>
            </div>
            <Button
              isIconOnly
              variant="light"
              size="sm"
              radius="full"
              aria-label="Minimize"
              className="size-6 min-w-6 p-0! text-zinc-500 hover:text-zinc-300"
              onPress={() => persistMinimized(true)}
            >
              <CancelIcon width={13} height={13} />
            </Button>
          </div>

          {overview.points > 0 && (
            <Progress
              aria-label="Referral progress"
              size="sm"
              color="primary"
              value={overview.progress_pct}
              className="mb-2"
            />
          )}

          <PopoverTrigger>
            <Button
              size="sm"
              variant="flat"
              className="w-full rounded-xl bg-zinc-900/60 text-xs text-zinc-300 hover:bg-zinc-900"
            >
              Share & earn
            </Button>
          </PopoverTrigger>
        </div>

        <PopoverContent className="w-[320px] rounded-2xl bg-zinc-900/90 p-4 backdrop-blur-2xl">
          <div className="w-full space-y-3">
            <div>
              <p className="text-sm font-medium text-zinc-100">
                {overview.next_goal_reward_months} month
                {overview.next_goal_reward_months === 1 ? "" : "s"} of PRO away
              </p>
              <p className="text-xs text-zinc-500">
                Every friend who subscribes earns you a free month.
              </p>
            </div>
            <ShareZone shareLink={overview.share_link} code={overview.code} />
            <Button
              size="sm"
              color="primary"
              variant="flat"
              className="w-full rounded-xl"
              onPress={() => router.push(HUB_ROUTE)}
            >
              See all rewards
            </Button>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}

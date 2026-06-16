"use client";

import { Button } from "@heroui/button";
import { Progress } from "@heroui/progress";
import { CancelIcon, GiftIcon } from "@icons";
import { useEffect, useState } from "react";
import { RaisedButton } from "@/components/ui/raised-button";
import { useReferralOverview } from "@/features/referrals";
import { useRouter } from "@/i18n/navigation";

const STORAGE_KEY = "sidebar-referral-promo-collapsed:v1";
const HUB_ROUTE = "/settings/referrals";

/**
 * Audience-aware sidebar slot for PRO users — replaces the upgrade nudge with a
 * referral nudge. Mirrors SidebarPromo's collapse/localStorage behaviour and
 * visual weight so there is never a second competing card.
 */
export function SidebarReferralPromo() {
  const router = useRouter();
  const { data: overview } = useReferralOverview();
  const [isCollapsed, setIsCollapsed] = useState(false);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) setIsCollapsed(JSON.parse(stored));
    } catch {
      // localStorage unavailable (e.g. incognito/Safari) — use default
    }
  }, []);

  const handleCollapse = () => {
    setIsCollapsed(true);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(true));
    } catch {
      // localStorage unavailable — state still updated in memory
    }
  };

  const goToHub = () => router.push(HUB_ROUTE);

  return (
    <div
      className={`group/referralsidebar flex flex-col justify-center transition-all duration-200 ${isCollapsed ? "mt-1 mb-2 w-full px-1" : "mb-2 h-fit w-fit rounded-2xl bg-zinc-800 p-4 pt-1"}`}
    >
      {!isCollapsed && (
        <>
          <div className="flex w-full items-center justify-between gap-1">
            <div className="text-sm font-medium">Give a month, get one</div>
            <Button
              isIconOnly
              variant="light"
              size="sm"
              radius="full"
              className="relative left-3 p-0! text-zinc-400 opacity-0 transition hover:text-white group-hover/referralsidebar:opacity-100"
              onPress={handleCollapse}
            >
              <CancelIcon width={15} height={15} />
            </Button>
          </div>
          <p className="text-xs text-zinc-400">
            Gift a friend GAIA Pro. Earn a free month when they subscribe.
          </p>
          {overview && overview.points > 0 && (
            <Progress
              aria-label="Referral progress"
              size="sm"
              color="primary"
              value={overview.progress_pct}
              className="mt-3"
            />
          )}
        </>
      )}

      <RaisedButton
        className={`w-full rounded-xl! text-black! ${isCollapsed ? "" : "mt-3"}`}
        color="#00bbff"
        size="sm"
        onClick={goToHub}
      >
        <GiftIcon fill="black" width={17} height={17} />
        Invite friends
      </RaisedButton>
    </div>
  );
}

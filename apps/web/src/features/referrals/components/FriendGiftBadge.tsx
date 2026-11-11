"use client";

import { Avatar } from "@heroui/avatar";
import type { ReferralFriendGift } from "@shared/api/generated";
import { REFERRAL_UI_COPY } from "../referralCopy";

interface FriendGiftBadgeProps {
  gift: ReferralFriendGift;
}

/** Whose gift a referred friend's struck-through price comes from, above their plan card. */
export function FriendGiftBadge({ gift }: FriendGiftBadgeProps) {
  const referrer = gift.referrer_first_name;
  return (
    <div className="flex items-center gap-2.5 rounded-full bg-zinc-800 py-1 pr-4 pl-1">
      <Avatar
        src={gift.referrer_picture ?? undefined}
        name={referrer ?? undefined}
        size="sm"
        className="size-7"
      />
      <span className="text-sm text-zinc-200">
        {referrer
          ? REFERRAL_UI_COPY.paywallGiftFrom(referrer)
          : REFERRAL_UI_COPY.paywallGiftFromSomeone}
      </span>
    </div>
  );
}

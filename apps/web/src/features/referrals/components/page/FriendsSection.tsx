import type { ReferredFriend } from "@shared/api/generated";
import type { ReactNode } from "react";
import { REFERRAL_UI_COPY } from "../../referralCopy";
import { FriendsList } from "../FriendsList";

interface FriendsSectionProps {
  friends: ReferredFriend[];
  /** Right side of the header row, e.g. the earned total in the minimal layout. */
  accessory?: ReactNode;
}

export function FriendsSection({ friends, accessory }: FriendsSectionProps) {
  return (
    <section className="flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h2 className="text-sm font-medium text-zinc-300">
          {REFERRAL_UI_COPY.friendsTitle}
          {friends.length > 0 && (
            <span className="ml-1.5 text-zinc-500 tabular-nums">
              {friends.length}
            </span>
          )}
        </h2>
        {accessory}
      </div>
      <FriendsList friends={friends} />
    </section>
  );
}

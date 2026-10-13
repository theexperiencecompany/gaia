import { Avatar } from "@heroui/avatar";
import { Chip } from "@heroui/chip";
import { ScrollShadow } from "@heroui/scroll-shadow";
import { Tooltip } from "@heroui/tooltip";
import { GiftIcon, UserAdd01Icon } from "@icons";
import type { ReferredFriend } from "@shared/api/generated";
import { formatDate } from "@shared/utils";
import { REFERRAL_UI_COPY } from "../referralCopy";

interface FriendsListProps {
  friends: ReferredFriend[];
}

export function FriendsList({ friends }: FriendsListProps) {
  if (friends.length === 0) {
    return (
      <div className="flex items-center gap-3 rounded-2xl bg-zinc-900/60 p-4">
        <div className="flex size-10 shrink-0 items-center justify-center rounded-full bg-zinc-800 text-zinc-400">
          <UserAdd01Icon width={18} height={18} />
        </div>
        <p className="text-sm text-pretty text-zinc-400">
          {REFERRAL_UI_COPY.friendsEmpty}
        </p>
      </div>
    );
  }

  return (
    <ScrollShadow className="max-h-80 rounded-2xl bg-zinc-900/60" hideScrollBar>
      <ul className="divide-y divide-zinc-800/60">
        {friends.map((friend) => (
          <FriendRow
            key={`${friend.joined_at}-${friend.first_name ?? ""}`}
            friend={friend}
          />
        ))}
      </ul>
    </ScrollShadow>
  );
}

function FriendRow({ friend }: { friend: ReferredFriend }) {
  const isPaid = friend.status === "paid";
  const name = friend.first_name ?? REFERRAL_UI_COPY.unnamedFriend;
  return (
    <li className="flex items-center gap-3 px-4 py-3">
      <Avatar name={name} size="sm" className="shrink-0" />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-zinc-200">{name}</p>
        <p className="text-xs text-zinc-500 tabular-nums">
          {friend.paid_at
            ? REFERRAL_UI_COPY.subscribedOn(formatDate(friend.paid_at))
            : REFERRAL_UI_COPY.joinedOn(formatDate(friend.joined_at))}
        </p>
      </div>
      {isPaid ? (
        <Chip
          size="sm"
          variant="flat"
          color="success"
          startContent={<GiftIcon width={13} height={13} className="ml-1" />}
        >
          {REFERRAL_UI_COPY.statusPaid}
        </Chip>
      ) : (
        <Tooltip content={REFERRAL_UI_COPY.pendingHint} delay={300}>
          <Chip size="sm" variant="flat" className="text-zinc-400">
            {REFERRAL_UI_COPY.statusPending}
          </Chip>
        </Tooltip>
      )}
    </li>
  );
}

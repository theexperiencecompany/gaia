"use client";

import { Chip } from "@heroui/chip";
import { formatDistanceToNow } from "date-fns";

import type { FriendReferral } from "../types";
import { presentStatus } from "./friendStatus";

function relativeTime(iso: string): string {
  try {
    return formatDistanceToNow(new Date(iso), { addSuffix: true });
  } catch {
    return "";
  }
}

function FriendRow({ friend }: { friend: FriendReferral }) {
  const { label, chipColor, dotClass } = presentStatus(friend.status);
  const when = relativeTime(friend.upgraded_at ?? friend.created_at);

  return (
    <div className="flex items-center gap-3 rounded-xl px-3 py-2.5 transition-colors hover:bg-white/5">
      <span className={`size-2 shrink-0 rounded-full ${dotClass}`} />
      <span className="min-w-0 flex-1 truncate text-sm text-zinc-200">
        {friend.display}
      </span>
      {when && <span className="shrink-0 text-xs text-zinc-600">{when}</span>}
      <Chip color={chipColor} variant="flat" size="sm" className="text-xs">
        {label}
      </Chip>
    </div>
  );
}

export function FriendsList({ friends }: { friends: FriendReferral[] }) {
  if (friends.length === 0) {
    return (
      <div className="rounded-2xl bg-zinc-900/60 px-5 py-8 text-center">
        <p className="text-sm text-zinc-400">No friends yet — but the first</p>
        <p className="text-sm text-zinc-400">
          invite is the hardest. Share your link and watch them roll in.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-0.5 rounded-2xl bg-zinc-900/60 p-2">
      {friends.map((friend) => (
        <FriendRow
          key={`${friend.display}-${friend.created_at}`}
          friend={friend}
        />
      ))}
    </div>
  );
}

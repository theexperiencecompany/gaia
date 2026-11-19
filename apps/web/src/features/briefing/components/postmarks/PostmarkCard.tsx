import type { Postmark } from "@shared/api/generated";
import Image from "next/image";

import { formatRelativeDate } from "@/utils/date/dateUtils";

interface PostmarkCardProps {
  postmark: Postmark;
}

/** A stamp's details: its art, its city, and the morning it arrived. */
export function PostmarkCard({ postmark }: PostmarkCardProps) {
  return (
    <div className="flex items-center gap-3 rounded-2xl bg-zinc-800 p-2 pr-4 shadow-xl shadow-black/40">
      <Image
        src={postmark.stamp_url}
        alt={`${postmark.city} stamp`}
        width={44}
        height={56}
        className="h-14 w-11 shrink-0 object-contain"
      />
      <div className="flex min-w-0 flex-col">
        <p className="truncate text-sm font-medium text-zinc-100">
          {postmark.city}
        </p>
        <p className="truncate text-xs text-zinc-400">{postmark.country}</p>
        <p className="mt-1 text-xs text-zinc-500 tabular-nums">
          {formatRelativeDate(postmark.date)}
        </p>
      </div>
    </div>
  );
}

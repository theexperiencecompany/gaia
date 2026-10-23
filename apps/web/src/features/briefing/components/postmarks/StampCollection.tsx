import { Tooltip } from "@heroui/tooltip";
import type { Postmark } from "@shared/api/generated";
import Image from "next/image";
import Link from "next/link";

import { cn } from "@/lib/utils";
import { PostmarkCard } from "./PostmarkCard";

interface StampCollectionProps {
  postmarks: Postmark[];
  total: number;
}

// The stamp art's own proportions, so a slot and a stamp occupy the same cell.
const STAMP_SLOT = "aspect-[600/850] w-full";

/** The album: collected stamps in arrival order, then an empty slot for each one still to come. */
export function StampCollection({ postmarks, total }: StampCollectionProps) {
  // An empty slot's album position (the stamp that will fill it) is its identity.
  const emptySlots = Array.from(
    { length: Math.max(total - postmarks.length, 0) },
    (_, offset) => postmarks.length + offset + 1,
  );
  return (
    <ul
      aria-label="Stamp collection"
      className="grid grid-cols-[repeat(auto-fill,minmax(72px,1fr))] gap-3"
    >
      {postmarks.map((postmark) => (
        <li key={postmark.city_slug}>
          <Tooltip
            content={<PostmarkCard postmark={postmark} />}
            classNames={{ content: "bg-transparent p-0 shadow-none" }}
            closeDelay={0}
          >
            <Link
              href={`/brief/${postmark.briefing_id}`}
              aria-label={`${postmark.city}, ${postmark.country}`}
              className={cn(
                STAMP_SLOT,
                "block transition-transform duration-200 ease-out hover:-translate-y-0.5 hover:-rotate-2",
              )}
            >
              <Image
                src={postmark.stamp_url}
                alt=""
                width={144}
                height={204}
                className="h-full w-full object-contain drop-shadow-[0_4px_10px_rgb(0_0_0/0.45)]"
              />
            </Link>
          </Tooltip>
        </li>
      ))}
      {emptySlots.map((slot) => (
        <li
          key={slot}
          aria-hidden
          className={cn(
            STAMP_SLOT,
            "flex items-center justify-center rounded-md bg-zinc-800/40",
          )}
        >
          <span className="h-[82%] w-[78%] rounded-sm bg-zinc-900/50" />
        </li>
      ))}
    </ul>
  );
}

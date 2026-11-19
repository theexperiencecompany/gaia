import { Tooltip } from "@heroui/react";
import type { Postmark } from "@shared/api/generated";
import Image from "next/image";
import Link from "next/link";
import { Focusable } from "react-aria-components";

import { overlayVariants } from "@/components/shared/controlVariants";
import { cn } from "@/lib/utils";
import { PostmarkCard } from "./PostmarkCard";

interface StampCollectionProps {
  postmarks: Postmark[];
  total: number;
}

// The stamp art's own proportions, so the to-come tile and a stamp occupy the same cell.
const STAMP_SLOT = "aspect-[600/850] w-full";

/**
 * The album: collected stamps in arrival order, then one tile counting the
 * cities still to come. Each stamp is captioned with its city below sm, where
 * there is no hover to reveal the tooltip.
 */
export function StampCollection({ postmarks, total }: StampCollectionProps) {
  const remaining = Math.max(total - postmarks.length, 0);
  return (
    <ul
      aria-label="Stamp collection"
      className="grid grid-cols-[repeat(auto-fill,minmax(72px,1fr))] gap-3"
    >
      {postmarks.map((postmark) => (
        <li key={postmark.city_slug}>
          <Tooltip closeDelay={0}>
            <Focusable>
              <Link
                href={`/brief/${postmark.briefing_id}`}
                aria-label={`${postmark.city}, ${postmark.country}`}
                className="group block"
              >
                <div
                  className={cn(
                    STAMP_SLOT,
                    "transition-transform duration-200 ease-out group-hover:-translate-y-0.5 group-hover:-rotate-2",
                  )}
                >
                  <Image
                    src={postmark.stamp_url}
                    alt=""
                    width={144}
                    height={204}
                    className="h-full w-full object-contain drop-shadow-[0_4px_10px_rgb(0_0_0/0.45)]"
                  />
                </div>
                <p className="mt-1 truncate text-center text-xs text-zinc-400 sm:hidden">
                  {postmark.city}
                </p>
              </Link>
            </Focusable>
            <Tooltip.Content
              placement="bottom"
              className={overlayVariants({ surface: "bare" })}
            >
              <PostmarkCard postmark={postmark} />
            </Tooltip.Content>
          </Tooltip>
        </li>
      ))}
      {remaining > 0 && (
        <li
          className={cn(
            STAMP_SLOT,
            "flex flex-col items-center justify-center gap-0.5 rounded-md bg-zinc-800/40 p-2 text-center",
          )}
        >
          <span className="text-lg font-medium text-zinc-300 tabular-nums">
            {remaining}
          </span>{" "}
          <span className="text-xs text-pretty text-zinc-500">
            {postmarks.length === 0
              ? `${remaining === 1 ? "city" : "cities"} to collect`
              : `more ${remaining === 1 ? "city" : "cities"}`}
          </span>
        </li>
      )}
    </ul>
  );
}

"use client";

import Image from "next/image";
import { cn } from "@/lib/utils";
import type { Release } from "../types";
import { formatReleaseDate } from "../utils/formatReleaseDate";

const FALLBACK_IMAGE = "/images/whats-new-fallback.png";

// How many of the latest releases to surface as quick-jump thumbnails.
const RECENT_COUNT = 3;

interface WhatsNewRecentReleasesProps {
  releases: Release[];
  currentIndex: number;
  onSelect: (index: number) => void;
}

/**
 * Footer grid at the bottom of the modal: the most recent releases as hoverable,
 * clickable image thumbnails that jump the modal to that release.
 */
export function WhatsNewRecentReleases({
  releases,
  currentIndex,
  onSelect,
}: Readonly<WhatsNewRecentReleasesProps>) {
  // `releases` is ordered most-recent-first, so the first N are the latest and
  // each item's position in the slice equals its index in the full list.
  const recent = releases.slice(0, RECENT_COUNT);
  if (recent.length < 2) return null;

  return (
    <div className="mt-6 border-t border-zinc-800 pt-4 pr-2 pb-2">
      <span className="mb-3 block text-xs font-medium text-zinc-500">
        Recent releases
      </span>
      <div className="grid grid-cols-3 gap-1">
        {recent.map((release, index) => {
          const isActive = index === currentIndex;
          return (
            <button
              key={release.id}
              type="button"
              onClick={() => onSelect(index)}
              aria-label={`View release: ${release.title}`}
              aria-current={isActive ? "true" : undefined}
              className={cn(
                "group/thumb flex min-w-0 cursor-pointer flex-col gap-2 rounded-xl p-2 text-left transition-colors hover:bg-zinc-800",
                isActive && "bg-zinc-800/60",
              )}
            >
              <div className="relative aspect-video w-full overflow-hidden rounded-lg bg-zinc-800">
                <Image
                  src={release.imageUrl ?? FALLBACK_IMAGE}
                  alt={release.title}
                  fill
                  sizes="220px"
                  className="object-cover transition duration-300 group-hover/thumb:scale-105"
                />
              </div>
              <div className="flex min-w-0 flex-col gap-0.5">
                <span className="block truncate text-xs font-medium text-zinc-300 transition group-hover/thumb:text-white">
                  {release.title}
                </span>
                <span className="text-[11px] text-zinc-500">
                  {formatReleaseDate(release.date)}
                </span>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

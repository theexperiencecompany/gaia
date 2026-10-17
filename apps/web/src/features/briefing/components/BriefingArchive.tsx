"use client";

import { Button } from "@heroui/button";
import { Link } from "@heroui/link";
import { Skeleton } from "@heroui/skeleton";

import { useBriefingsQuery } from "../hooks/useBriefingsQuery";
import { BriefingEdition } from "./BriefingEdition";

export interface BriefingArchiveProps {
  limit?: number;
  className?: string;
}

/** The latest brief in full (its edition, then its items); every earlier one links to its page. */
export function BriefingArchive({
  limit = 30,
  className,
}: BriefingArchiveProps) {
  const {
    data: briefings,
    isLoading,
    isError,
    refetch,
  } = useBriefingsQuery(limit);

  if (isLoading) {
    return (
      <div className={className}>
        <Skeleton className="h-[60vh] w-full rounded-2xl" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex items-center gap-3">
        <p className="text-sm text-zinc-500">Couldn't load your briefings.</p>
        <Button size="sm" variant="flat" onPress={() => refetch()}>
          Try again
        </Button>
      </div>
    );
  }

  if (!briefings || briefings.length === 0) {
    return <p className="text-sm text-zinc-500">No past briefings yet.</p>;
  }

  const [latest, ...earlier] = briefings;
  return (
    <div className={className}>
      <BriefingEdition
        payload={latest.payload}
        imageUrl={latest.edition_image_url}
      />
      {earlier.length > 0 && (
        <div className="mt-4 rounded-2xl bg-zinc-800 p-4">
          <p className="mb-3 text-sm font-semibold text-zinc-100">Earlier</p>
          <div className="space-y-2">
            {earlier.map((briefing) => (
              <Link
                key={briefing.id}
                href={`/brief/${briefing.id}`}
                className="block rounded-2xl bg-zinc-900 p-3 transition-colors hover:bg-white/5"
              >
                <p className="text-sm font-medium text-zinc-200">
                  {briefing.payload.headline}
                </p>
                <p className="text-xs text-zinc-500">{briefing.date}</p>
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

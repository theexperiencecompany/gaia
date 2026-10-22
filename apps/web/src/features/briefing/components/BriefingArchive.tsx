"use client";

import { Button } from "@heroui/button";
import { Skeleton } from "@heroui/skeleton";

import { useBriefingsQuery } from "../hooks/useBriefingsQuery";
import { BriefingFold } from "./BriefingFold";

export interface BriefingArchiveProps {
  limit?: number;
  className?: string;
}

/** Every brief folded to its edition and headline, newest first; each opens as a letter. */
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
        <Skeleton className="h-24 w-full max-w-md rounded-2xl" />
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

  return (
    <div className={className}>
      <div className="flex flex-col gap-2">
        {briefings.map((briefing) => (
          <BriefingFold
            key={briefing.id}
            headline={briefing.payload.headline}
            date={briefing.date}
            imageUrl={briefing.edition_image_url}
            payload={briefing.payload}
          />
        ))}
      </div>
    </div>
  );
}

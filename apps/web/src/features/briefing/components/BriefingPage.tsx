"use client";

import { Button } from "@heroui/button";
import { Skeleton } from "@heroui/skeleton";
import Link from "next/link";

import { StandalonePage } from "@/components/layout/StandalonePage";

import { useBriefingQuery } from "../hooks/useBriefingQuery";
import { StandaloneBriefing } from "./StandaloneBriefing";

/** The /brief/[id] page: loads the signed-in reader's brief into the standalone shell. */
export function BriefingPage({ briefingId }: { briefingId: string }) {
  const { data: briefing, isLoading, isError } = useBriefingQuery(briefingId);

  if (isLoading) {
    return (
      <StandalonePage>
        <Skeleton className="mx-auto h-[70vh] w-full max-w-[540px] rounded-2xl" />
      </StandalonePage>
    );
  }
  if (isError || !briefing) {
    return (
      <StandalonePage>
        <div className="flex flex-col items-center gap-4 py-24 text-center">
          <p className="text-sm text-zinc-400">
            This brief isn&apos;t available anymore.
          </p>
          <Button as={Link} href="/briefings" variant="flat" size="sm">
            Open your briefings
          </Button>
        </div>
      </StandalonePage>
    );
  }
  return (
    <StandaloneBriefing briefing={briefing} ownedBriefingId={briefingId} />
  );
}

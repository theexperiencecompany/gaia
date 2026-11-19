"use client";

import { Skeleton } from "@heroui/react";

import { StandalonePage } from "@/components/layout/StandalonePage";
import { LinkButton } from "@/components/shared/LinkButton";

import { BACK_TO_BRIEFINGS } from "../constants";
import { useBriefingQuery } from "../hooks/useBriefingQuery";
import { StandaloneBriefing } from "./StandaloneBriefing";

/** The /brief/[id] page: loads the signed-in reader's brief into the standalone shell. */
export function BriefingPage({ briefingId }: { briefingId: string }) {
  const { data: briefing, isLoading, isError } = useBriefingQuery(briefingId);

  if (isLoading) {
    return (
      <StandalonePage width="letter" back={BACK_TO_BRIEFINGS}>
        <Skeleton className="mx-auto h-[70vh] w-full max-w-[540px] rounded-2xl" />
      </StandalonePage>
    );
  }
  if (isError || !briefing) {
    return (
      <StandalonePage width="letter" back={BACK_TO_BRIEFINGS}>
        <div className="flex flex-col items-center gap-4 py-24 text-center">
          <p className="text-sm text-zinc-400">
            This brief isn&apos;t available anymore.
          </p>
          <LinkButton href="/briefings" variant="default-soft" size="sm">
            Open your briefings
          </LinkButton>
        </div>
      </StandalonePage>
    );
  }
  return (
    <StandaloneBriefing briefing={briefing} ownedBriefingId={briefingId} />
  );
}

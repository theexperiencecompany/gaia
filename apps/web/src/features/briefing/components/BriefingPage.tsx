"use client";

import { Skeleton } from "@heroui/react";
import { useQuery } from "@tanstack/react-query";

import { StandalonePage } from "@/components/layout/StandalonePage";
import { LinkButton } from "@/components/shared/LinkButton";
import { LoadError } from "@/components/shared/LoadError";
import { isNotFound } from "@/lib/api/errorMessage";
import { cn } from "@/lib/utils";
import { briefingQuery } from "../api/briefingApi";
import { BACK_TO_BRIEFINGS } from "../constants";
import { BRIEF_PAGE_COLUMN_CLASS } from "../letterTokens";
import { StandaloneBriefing } from "./StandaloneBriefing";

/** The /brief/[id] page: loads the signed-in reader's brief into the standalone shell. */
export function BriefingPage({ briefingId }: { briefingId: string }) {
  const {
    data: briefing,
    isLoading,
    error,
    refetch,
  } = useQuery(briefingQuery(briefingId));

  if (isLoading) {
    return (
      <StandalonePage width="letter" back={BACK_TO_BRIEFINGS}>
        <Skeleton
          className={cn(
            "mx-auto h-[70vh] w-full rounded-2xl",
            BRIEF_PAGE_COLUMN_CLASS,
          )}
        />
      </StandalonePage>
    );
  }
  if (error && !isNotFound(error)) {
    return (
      <StandalonePage width="letter" back={BACK_TO_BRIEFINGS}>
        <LoadError
          className="mx-auto mt-24 max-w-md"
          title="Couldn't load this brief"
          description="It's still in your briefings. This page just couldn't reach it."
          onRetry={() => void refetch()}
        />
      </StandalonePage>
    );
  }
  if (!briefing) {
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

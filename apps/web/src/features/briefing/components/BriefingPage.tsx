"use client";

import { Skeleton } from "@heroui/skeleton";

import { useBriefingQuery } from "../hooks/useBriefingQuery";
import { StandaloneBriefing } from "./StandaloneBriefing";

/** The /brief/[id] page: loads the signed-in reader's brief into the standalone shell. */
export function BriefingPage({ briefingId }: { briefingId: string }) {
  const { data: briefing, isLoading, isError } = useBriefingQuery(briefingId);

  if (isLoading) {
    return (
      <main className="min-h-screen w-full bg-primary-bg px-4 py-6">
        <Skeleton className="mx-auto h-[70vh] w-full max-w-3xl rounded-2xl" />
      </main>
    );
  }
  if (isError || !briefing) {
    return (
      <main className="flex min-h-screen w-full items-center justify-center bg-primary-bg px-4">
        <p className="text-sm text-zinc-400">
          This brief isn&apos;t available. It may belong to another account.
        </p>
      </main>
    );
  }
  return <StandaloneBriefing briefing={briefing} />;
}

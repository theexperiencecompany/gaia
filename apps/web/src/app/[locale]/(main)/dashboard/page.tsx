"use client";

import { Skeleton } from "@heroui/skeleton";
import { DoneRow } from "@/features/dashboard/components/DoneRow";
import { InFlightRow } from "@/features/dashboard/components/InFlightRow";
import { NeedsYouRow } from "@/features/dashboard/components/NeedsYouRow";
import { SuggestedRow } from "@/features/dashboard/components/SuggestedRow";
import { TodayHeader } from "@/features/dashboard/components/TodayHeader";
import { TodaySection } from "@/features/dashboard/components/TodaySection";
import { YourTaskRow } from "@/features/dashboard/components/YourTaskRow";
import { useTodayLiveUpdates } from "@/features/dashboard/hooks/useTodayLiveUpdates";
import { useTodayQuery } from "@/features/dashboard/hooks/useTodayQuery";
import { useTrackRouteVisit } from "@/features/first-steps/hooks/useTrackRouteVisit";

function TodaySkeleton() {
  return (
    <div className="flex flex-col gap-6 px-3">
      <div className="flex flex-col gap-3">
        <Skeleton className="h-8 w-3/4 rounded-lg" />
        <Skeleton className="h-4 w-1/2 rounded-lg" />
      </div>
      {[0, 1, 2].map((section) => (
        <div key={section} className="flex flex-col gap-2">
          <Skeleton className="h-3 w-24 rounded-lg" />
          <Skeleton className="h-10 w-full rounded-xl" />
          <Skeleton className="h-10 w-full rounded-xl" />
        </div>
      ))}
    </div>
  );
}

export default function HomePage() {
  useTrackRouteVisit("visit_dashboard");
  useTodayLiveUpdates();

  const { data, isLoading } = useTodayQuery();

  const isEmpty =
    !!data &&
    data.needs_you.length === 0 &&
    data.suggested.length === 0 &&
    data.in_flight.length === 0 &&
    data.your_tasks.length === 0 &&
    data.done_today.length === 0;

  return (
    <div className="mx-auto flex h-fit min-h-screen w-full max-w-3xl flex-col gap-8 overflow-y-scroll p-6 pt-10 outline-none">
      {isLoading || !data ? (
        <TodaySkeleton />
      ) : (
        <>
          <TodayHeader
            headline={data.headline}
            subline={data.subline}
            runs={data.runs}
          />

          <TodaySection label="Needs you" count={data.needs_you.length}>
            {data.needs_you.map((item) => (
              <NeedsYouRow key={item.todo_id} item={item} />
            ))}
          </TodaySection>

          <TodaySection label="Suggested" count={data.suggested.length}>
            {data.suggested.map((item) => (
              <SuggestedRow key={item.todo_id} item={item} />
            ))}
          </TodaySection>

          <TodaySection label="In flight" count={data.in_flight.length}>
            {data.in_flight.map((item) => (
              <InFlightRow key={item.todo_id} item={item} />
            ))}
          </TodaySection>

          <TodaySection label="Your tasks" count={data.your_tasks.length}>
            {data.your_tasks.map((item) => (
              <YourTaskRow key={item.todo_id} item={item} />
            ))}
          </TodaySection>

          <TodaySection label="Done today" count={data.done_today.length}>
            {data.done_today.map((item) => (
              <DoneRow key={item.todo_id} item={item} />
            ))}
          </TodaySection>

          {isEmpty && (
            <p className="px-3 text-sm text-zinc-500">
              Nothing on the board yet. Chat with GAIA about a goal and
              tomorrow's briefing will have something to show.
            </p>
          )}
        </>
      )}
    </div>
  );
}

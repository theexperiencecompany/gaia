"use client";

import { Skeleton } from "@heroui/skeleton";
import type React from "react";
import { useTrackRouteVisit } from "@/features/first-steps/hooks/useTrackRouteVisit";
import { useTodayLiveUpdates } from "@/features/todo/hooks/useTodayLiveUpdates";
import { useTodayQuery } from "@/features/todo/hooks/useTodayQuery";
import { DoneRow } from "./DoneRow";
import { InFlightRow } from "./InFlightRow";
import { NeedsYouRow } from "./NeedsYouRow";
import { SuggestedRow } from "./SuggestedRow";
import { TodayHeader } from "./TodayHeader";
import { TodaySection } from "./TodaySection";
import { YourTaskRow } from "./YourTaskRow";

function TodaySkeleton() {
  return (
    <div className="flex flex-col gap-6 px-4 pt-6">
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

/**
 * The top of the todos page: briefing headline/subline, then flat
 * status-grouped sections (needs you, suggested, in flight, your tasks, done
 * today). Each `TodaySection` renders nothing when empty, so a user with no
 * GAIA activity sees just the greeting strip above the regular todo list.
 */
export const TodayView: React.FC = () => {
  useTrackRouteVisit("visit_dashboard");
  useTodayLiveUpdates();

  const { data, isLoading } = useTodayQuery();

  if (isLoading || !data) {
    return <TodaySkeleton />;
  }

  return (
    <div className="flex w-full shrink-0 flex-col gap-6 px-4 pt-6 pb-4">
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
    </div>
  );
};

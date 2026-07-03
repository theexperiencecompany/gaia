"use client";

import { Avatar } from "@heroui/avatar";
import { getSimpleTimeGreeting } from "@shared/utils";
import { useState } from "react";
import { useUser } from "@/features/auth/hooks/useUser";
import { BriefingCard } from "@/features/briefing/components/BriefingCard";
import { useLatestBriefingQuery } from "@/features/briefing/hooks/useLatestBriefingQuery";
import { ActionRail } from "@/features/dashboard/components/ActionRail";
import { ContributionHeatmap } from "@/features/dashboard/components/ContributionHeatmap";
import { TodayTimeline } from "@/features/dashboard/components/TodayTimeline";
import { useHeatmapQuery } from "@/features/dashboard/hooks/useHeatmapQuery";
import { useTodayQuery } from "@/features/dashboard/hooks/useTodayQuery";
import { useTrackRouteVisit } from "@/features/first-steps/hooks/useTrackRouteVisit";
import { useTodoData } from "@/features/todo/hooks/useTodoData";

function GreetingHeader() {
  const user = useUser();
  const simpleGreeting = getSimpleTimeGreeting();

  return (
    <div className="flex items-center gap-3 rounded-2xl bg-zinc-800 p-5">
      {user?.profilePicture && (
        <Avatar
          src={user.profilePicture}
          name={user.name || "User"}
          size="md"
          className="shrink-0"
        />
      )}
      <div>
        <h1 className="text-xl font-medium text-zinc-100">
          {simpleGreeting}, {user?.name?.split(" ")[0]}
        </h1>
        <p className="text-sm text-zinc-500">
          Here's where things stand today.
        </p>
      </div>
    </div>
  );
}

export default function HomePage() {
  useTrackRouteVisit("visit_dashboard");

  const [briefingCollapsed, setBriefingCollapsed] = useState(false);

  const { data: briefing, isLoading: briefingLoading } =
    useLatestBriefingQuery();
  const { data: todayData, isLoading: todayLoading } = useTodayQuery();
  const { data: heatmapData, isLoading: heatmapLoading } = useHeatmapQuery();
  const { todos, loading: todosLoading } = useTodoData();

  return (
    <div className="mx-auto flex h-fit min-h-screen w-full max-w-4xl flex-col gap-6 overflow-y-scroll p-6 pt-0 outline-none">
      {!briefingLoading && briefing ? (
        <BriefingCard
          payload={briefing.payload}
          collapsed={briefingCollapsed}
          onCollapsedChange={setBriefingCollapsed}
        />
      ) : (
        !briefingLoading && <GreetingHeader />
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <TodayTimeline data={todayData} isLoading={todayLoading} />
        </div>
        <ActionRail
          todos={todos}
          todosLoading={todosLoading}
          todayData={todayData}
        />
      </div>

      <ContributionHeatmap data={heatmapData} isLoading={heatmapLoading} />
    </div>
  );
}

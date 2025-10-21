"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { SidebarHeaderButton } from "@/components/layout/headers/HeaderManager";
import { ChatBubbleAddIcon, Target02Icon } from "@/components/shared/icons";
import { NotificationCenter } from "@/features/notification/components/NotificationCenter";
import { goalsApi } from "@/features/goals/api/goalsApi";
import { Goal } from "@/types/api/goalsApiTypes";
import { ChevronRight } from "lucide-react";

export default function GoalHeader() {
  const params = useParams();
  const goalId = typeof params.id === "string" ? params.id : params.id?.[0];
  const [goal, setGoal] = useState<Goal | null>(null);

  useEffect(() => {
    if (goalId) {
      goalsApi
        .fetchGoalById(goalId)
        .then((data) => setGoal(data as Goal))
        .catch(() => setGoal(null));
    }
  }, [goalId]);

  return (
    <div className="flex w-full items-center justify-between">
      <div className="flex items-center gap-2 pl-2 text-zinc-500">
        <Link href={"/goals"} className="flex items-center gap-2">
          <Target02Icon width={20} height={20} color={undefined} />
          <span>Goals</span>
        </Link>
        {goal?.title && (
          <>
            <ChevronRight width={18} height={17} />
            <span className="text-zinc-300">{goal.title}</span>
          </>
        )}
      </div>

      <div className="relative z-[100] flex items-center">
        <Link href={"/c"}>
          <SidebarHeaderButton
            aria-label="Create new chat"
            tooltip="Create new chat"
          >
            <ChatBubbleAddIcon className="min-h-[20px] min-w-[20px] text-zinc-400 transition-all group-hover:text-primary" />
          </SidebarHeaderButton>
        </Link>
        <NotificationCenter />
      </div>
    </div>
  );
}

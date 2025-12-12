"use client";

import { useRouter } from "next/navigation";
import { memo, useCallback, useMemo } from "react";

import BaseCardView from "@/features/chat/components/interface/BaseCardView";
import { Target02Icon } from "@/icons";
import type { Goal } from "@/types/api/goalsApiTypes";

interface GoalsViewProps {
  goals?: Goal[];
}

const GoalsView = memo(({ goals = [] }: GoalsViewProps) => {
  const router = useRouter();

  const handleGoalClick = useCallback(
    (goalId: string) => {
      router.push(`/goals/${goalId}`);
    },
    [router],
  );

  // Memoize first 5 goals
  const displayGoals = useMemo(() => goals.slice(0, 5), [goals]);

  const isEmpty = goals.length === 0;

  return (
    <BaseCardView
      title="Goals"
      icon={<Target02Icon className="h-6 w-6 text-zinc-500" />}
      isEmpty={isEmpty}
      emptyMessage="No goals created yet"
      errorMessage="Failed to load goals"
      path="/goals"
    >
      <div className="space-y-0">
        {displayGoals.map((goal) => (
          <div
            key={goal.id}
            className="flex cursor-pointer items-start gap-3 p-4 transition-colors hover:bg-zinc-700/30"
            onClick={() => handleGoalClick(goal.id)}
          >
            <div className="min-w-0 flex-1">
              <h4 className="text-base font-medium text-white">{goal.title}</h4>
              {goal.description && (
                <p className="mt-1 text-xs text-zinc-400 line-clamp-2">
                  {goal.description}
                </p>
              )}
            </div>
          </div>
        ))}
      </div>
    </BaseCardView>
  );
});

GoalsView.displayName = "GoalsView";

export default GoalsView;

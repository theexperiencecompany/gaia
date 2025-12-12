"use client";

import { useRouter } from "next/navigation";
import { memo, useCallback, useEffect, useMemo, useRef } from "react";

import BaseCardView from "@/features/chat/components/interface/BaseCardView";
import { useGoals } from "@/features/goals/hooks/useGoals";
import { Loading02Icon, Target02Icon } from "@/icons";

const GoalsView = memo(() => {
  const router = useRouter();
  const { goals, loading, fetchGoals } = useGoals();
  const hasLoadedRef = useRef(false);

  // Only fetch once on mount
  useEffect(() => {
    if (!hasLoadedRef.current) {
      hasLoadedRef.current = true;
      fetchGoals();
    }
  }, [fetchGoals]);

  const handleRefresh = useCallback(() => {
    fetchGoals();
  }, [fetchGoals]);

  const handleGoalClick = useCallback(
    (goalId: string) => {
      router.push(`/goals/${goalId}`);
    },
    [router],
  );

  // Memoize first 5 goals
  const displayGoals = useMemo(() => goals.slice(0, 5), [goals]);

  const isEmpty = !loading && goals.length === 0;

  return (
    <BaseCardView
      title="Goals"
      icon={<Target02Icon className="h-6 w-6 text-zinc-500" />}
      isFetching={loading}
      isEmpty={isEmpty}
      emptyMessage="No goals created yet"
      errorMessage="Failed to load goals"
      path="/goals"
      onRefresh={handleRefresh}
    >
      {loading ? (
        <div className="flex h-full items-center justify-center">
          <Loading02Icon className="h-8 w-8 animate-spin text-zinc-500" />
        </div>
      ) : (
        <div className="space-y-0">
          {displayGoals.map((goal) => (
            <div
              key={goal.id}
              className="flex cursor-pointer items-start gap-3 p-4 transition-colors hover:bg-zinc-700/30"
              onClick={() => handleGoalClick(goal.id)}
            >
              <div className="min-w-0 flex-1">
                <h4 className="text-base font-medium text-white">
                  {goal.title}
                </h4>
                {goal.description && (
                  <p className="mt-1 text-xs text-zinc-400 line-clamp-2">
                    {goal.description}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </BaseCardView>
  );
});

GoalsView.displayName = "GoalsView";

export default GoalsView;

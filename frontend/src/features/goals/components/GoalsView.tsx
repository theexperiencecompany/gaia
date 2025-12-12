"use client";

import { Chip } from "@heroui/chip";
import { useRouter } from "next/navigation";
import { memo, useCallback, useMemo } from "react";

import BaseCardView from "@/features/chat/components/interface/BaseCardView";
import { Calendar03Icon, CheckmarkCircle02Icon, Target02Icon } from "@/icons";
import type { Goal } from "@/types/api/goalsApiTypes";
import { formatDate } from "@/utils";

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

  // Helper function to calculate steps completion
  const getStepsInfo = useCallback((goal: Goal) => {
    const nodes = goal.roadmap?.nodes || [];
    const totalSteps = nodes.length;
    const completedSteps = nodes.filter((node) => node.data?.isComplete).length;
    return { totalSteps, completedSteps };
  }, []);

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
        {displayGoals.map((goal) => {
          const { totalSteps, completedSteps } = getStepsInfo(goal);
          const hasSteps = totalSteps > 0;
          const progress = goal?.progress || 0;

          return (
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

                {/* Progress bar */}
                {hasSteps && (
                  <div className="mt-2 flex items-center gap-2">
                    <div className="relative h-2 flex-1 rounded-full">
                      <div
                        className="absolute top-0 left-0 z-[2] h-2 rounded-full bg-primary"
                        style={{ width: `${progress}%` }}
                      />
                      <div className="absolute top-0 left-0 h-2 w-full rounded-full bg-zinc-900" />
                    </div>
                    <span className="text-xs text-zinc-400 min-w-[2.5rem]">
                      {progress}%
                    </span>
                  </div>
                )}

                {/* Chips section */}
                <div className="mt-2 flex flex-wrap items-center gap-1">
                  {/* Status chip */}
                  <Chip
                    color={
                      !goal.roadmap?.nodes?.length ||
                      !goal.roadmap?.edges?.length
                        ? "warning"
                        : progress === 100
                          ? "success"
                          : progress > 0
                            ? "primary"
                            : "warning"
                    }
                    size="sm"
                    variant="flat"
                  >
                    {!goal.roadmap?.nodes?.length ||
                    !goal.roadmap?.edges?.length
                      ? "Not Started"
                      : progress === 100
                        ? "Completed"
                        : progress > 0
                          ? "In Progress"
                          : "Not Started"}
                  </Chip>

                  {/* Steps chip */}
                  {hasSteps && (
                    <Chip
                      size="sm"
                      variant="flat"
                      className="text-zinc-400 px-1"
                      radius="sm"
                      startContent={
                        <CheckmarkCircle02Icon
                          width={15}
                          height={15}
                          className="mx-1"
                        />
                      }
                    >
                      {completedSteps}/{totalSteps} steps
                    </Chip>
                  )}

                  {/* Created date chip */}
                  {goal.created_at && (
                    <Chip
                      size="sm"
                      variant="flat"
                      className="text-zinc-400 px-1"
                      radius="sm"
                      startContent={
                        <Calendar03Icon
                          width={15}
                          height={15}
                          className="mx-1"
                        />
                      }
                    >
                      {formatDate(goal.created_at)}
                    </Chip>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </BaseCardView>
  );
});

GoalsView.displayName = "GoalsView";

export default GoalsView;

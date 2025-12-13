"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import {
  ChartIcon,
  ChartIncreaseIcon,
  CheckmarkCircle02Icon,
  Target02Icon,
  Timer02Icon,
  UserGroupIcon,
  ZapIcon,
} from "@/icons";

import { GoalCard } from "./GoalCard";
import type { GoalSectionProps } from "./types";

export default function GoalSection({
  goals,
  stats,
  action = "list",
  message,
  goal_id,
  deleted_goal_id: _deleted_goal_id,
  error,
}: GoalSectionProps) {
  const router = useRouter();
  const [expandedGoals, setExpandedGoals] = useState<Set<string>>(new Set());

  const toggleGoalExpansion = (goalId: string) => {
    const newExpanded = new Set(expandedGoals);
    if (newExpanded.has(goalId)) {
      newExpanded.delete(goalId);
    } else {
      newExpanded.add(goalId);
    }
    setExpandedGoals(newExpanded);
  };

  const handleViewGoal = (goalId: string) => {
    router.push(`/goals/${goalId}`);
  };

  const handleViewTasks = (projectId: string) => {
    router.push(`/todos/project/${projectId}`);
  };

  // Error State
  if (error) {
    return (
      <div className="mt-3 w-fit min-w-[300px] rounded-2xl rounded-bl-none bg-zinc-800 p-4">
        <div className="flex items-center gap-2">
          <CheckmarkCircle02Icon className="h-4 w-4 text-red-500" />
          <p className="text-sm text-red-400">{error}</p>
        </div>
      </div>
    );
  }

  // Statistics View
  if (action === "stats" && stats) {
    return (
      <div className="mt-3 w-fit min-w-[400px] rounded-2xl rounded-bl-none bg-zinc-800 p-4">
        <div className="mb-3 flex items-center gap-2 text-sm">
          <ChartIcon className="h-4 w-4 text-primary" />
          Goal Progress Overview
        </div>
        <div className="grid grid-cols-3 gap-2">
          <div className="rounded-xl bg-zinc-900 p-3 text-center">
            <p className="text-xl font-semibold text-zinc-100">
              {stats.total_goals}
            </p>
            <p className="text-xs text-zinc-500">Total Goals</p>
          </div>
          <div className="rounded-xl bg-zinc-900 p-3 text-center">
            <p className="text-xl font-semibold text-primary">
              {stats.goals_with_roadmaps}
            </p>
            <p className="text-xs text-zinc-500">With Roadmaps</p>
          </div>
          <div className="rounded-xl bg-zinc-900 p-3 text-center">
            <p className="text-xl font-semibold text-green-500">
              {stats.overall_completion_rate}%
            </p>
            <p className="text-xs text-zinc-500">Complete</p>
          </div>
          <div className="rounded-xl bg-zinc-900 p-3 text-center">
            <p className="text-xl font-semibold text-blue-500">
              {stats.total_tasks}
            </p>
            <p className="text-xs text-zinc-500">Total Tasks</p>
          </div>
          <div className="rounded-xl bg-zinc-900 p-3 text-center">
            <p className="text-xl font-semibold text-green-500">
              {stats.completed_tasks}
            </p>
            <p className="text-xs text-zinc-500">Done Tasks</p>
          </div>
          <div className="rounded-xl bg-zinc-900 p-3 text-center">
            <p className="text-xl font-semibold text-orange-500">
              {stats.active_goals_count}
            </p>
            <p className="text-xs text-zinc-500">Active</p>
          </div>
        </div>

        {stats.active_goals && stats.active_goals.length > 0 && (
          <div className="mt-4">
            <p className="mb-2 text-xs font-medium text-zinc-500">
              Top Active Goals
            </p>
            <div className="space-y-2">
              {stats.active_goals.map((goal) => (
                <GoalCard
                  key={goal.id}
                  goal={goal}
                  variant="compact"
                  showActions={false}
                  showExpandToggle={false}
                  onViewGoal={handleViewGoal}
                />
              ))}
            </div>
          </div>
        )}
      </div>
    );
  }

  // Progress/Loading Messages
  if (
    [
      "creating",
      "fetching",
      "deleting",
      "updating_progress",
      "generating_roadmap",
    ].includes(action)
  ) {
    const icons = {
      creating: <ZapIcon className="h-4 w-4 text-blue-500" />,
      fetching: <Timer02Icon className="h-4 w-4 text-blue-500" />,
      deleting: <Timer02Icon className="h-4 w-4 text-red-500" />,
      updating_progress: (
        <ChartIncreaseIcon className="h-4 w-4 text-green-500" />
      ),
      generating_roadmap: <UserGroupIcon className="h-4 w-4 text-primary" />,
    };

    return (
      <div className="mt-3 w-fit rounded-2xl rounded-bl-none bg-zinc-800 p-4">
        <div className="flex items-center gap-2">
          {icons[action as keyof typeof icons] || (
            <Timer02Icon className="h-4 w-4 text-blue-500" />
          )}
          <p className="text-sm">{message}</p>
        </div>
      </div>
    );
  }

  // Roadmap needed message
  if (action === "roadmap_needed" && message) {
    return (
      <div className="mt-3 w-fit min-w-[350px] rounded-2xl rounded-bl-none bg-zinc-800 p-4">
        <div className="mb-3 flex items-center gap-2">
          <UserGroupIcon className="h-4 w-4 text-primary" />
          <p className="text-sm text-zinc-300">{message}</p>
        </div>
        <button
          type="button"
          onClick={() => router.push(`/goals/${goal_id}`)}
          className="w-full rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
        >
          Generate Roadmap
        </button>
      </div>
    );
  }

  // Create Goal Card - clean and simple design
  if (action === "create" && goals && goals.length === 1) {
    return (
      <div className="mt-3">
        <GoalCard
          goal={goals[0]}
          variant="create"
          showActions={true}
          showExpandToggle={false}
          onViewGoal={handleViewGoal}
        />
      </div>
    );
  }

  // Goals List View
  if (goals && goals.length > 0) {
    return (
      <div className="mt-3 w-fit min-w-[450px] rounded-2xl rounded-bl-none bg-zinc-800 p-4">
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm">
            <Target02Icon className="h-4 w-4 text-primary" />
            {action === "search"
              ? "Search Results"
              : action === "roadmap_generated"
                ? "Goal with Roadmap"
                : action === "node_updated"
                  ? "Updated Progress"
                  : "Your Goals"}
          </div>
          <span className="text-xs text-zinc-500">
            {goals.length} {goals.length === 1 ? "goal" : "goals"}
          </span>
        </div>
        <div className="space-y-3">
          {goals.map((goal) => (
            <GoalCard
              key={goal.id}
              goal={goal}
              variant="default"
              showActions={true}
              showExpandToggle={true}
              isExpanded={expandedGoals.has(goal.id)}
              onToggleExpand={toggleGoalExpansion}
              onViewGoal={handleViewGoal}
              onViewTasks={handleViewTasks}
            />
          ))}
        </div>
        {message && <p className="mt-3 text-xs text-zinc-500">{message}</p>}
      </div>
    );
  }

  // Empty State
  if (action === "list" && (!goals || goals.length === 0)) {
    return (
      <div className="mt-3 w-fit min-w-[300px] rounded-2xl rounded-bl-none bg-zinc-800 p-6 text-center">
        <Target02Icon className="mx-auto h-8 w-8 text-zinc-600" />
        <p className="mt-2 text-sm text-zinc-300">No goals found</p>
        {message && <p className="mt-1 text-xs text-zinc-500">{message}</p>}
      </div>
    );
  }

  // Success/Action Message
  if (message && !goals && !stats) {
    const isDeleteAction = action === "delete";
    const isSuccessAction = [
      "create",
      "roadmap_generated",
      "node_updated",
    ].includes(action);
    const iconColor = isDeleteAction
      ? "text-red-500"
      : isSuccessAction
        ? "text-green-500"
        : "text-blue-500";
    const icon = isDeleteAction
      ? CheckmarkCircle02Icon
      : isSuccessAction
        ? CheckmarkCircle02Icon
        : Target02Icon;
    const IconComponent = icon;

    return (
      <div className="mt-3 w-fit rounded-2xl rounded-bl-none bg-zinc-800 p-4">
        <div className="flex items-center gap-2">
          <IconComponent className={`h-4 w-4 ${iconColor}`} />
          <p className="text-sm">{message}</p>
        </div>
      </div>
    );
  }

  return null;
}

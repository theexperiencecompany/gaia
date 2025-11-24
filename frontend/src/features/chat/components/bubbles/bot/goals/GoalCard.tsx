"use client";

import { format } from "date-fns";

import {
  ArrowRight01Icon,
  Award01Icon,
  CalendarIcon,
  CheckmarkCircle02Icon,
  Target02Icon,
  UserGroupIcon,
} from "@/icons";

import type {
  GoalCardActionsProps,
  GoalCardContainerProps,
  GoalCardContentProps,
  GoalCardHeaderProps,
  GoalCardProps,
} from "./types";

// Modular Goal Card Components
function GoalCardContainer({
  variant = "default",
  children,
  onClick,
  className = "",
}: GoalCardContainerProps) {
  const baseClasses = "transition-colors";

  const variantClasses = {
    default: "rounded-xl bg-zinc-900 p-4",
    create: "w-full max-w-3xl overflow-hidden rounded-3xl bg-zinc-800",
    compact:
      "flex cursor-pointer items-center justify-between rounded-xl bg-zinc-900 p-4 hover:bg-zinc-800",
  };

  return (
    <div
      className={`${baseClasses} ${variantClasses[variant]} ${className}`}
      onClick={onClick}
    >
      {children}
    </div>
  );
}

function GoalCardHeader({
  title,
  variant = "default",
  icon,
  subtitle,
  progress,
  showExpandToggle = false,
  isExpanded = false,
  onToggleExpand,
}: GoalCardHeaderProps) {
  const getProgressColor = (progress: number) => {
    if (progress >= 90) return "text-green-500";
    if (progress >= 75) return "text-blue-500";
    if (progress >= 50) return "text-yellow-500";
    if (progress >= 25) return "text-orange-500";
    return "text-red-500";
  };

  if (variant === "create") {
    return (
      <div className="flex items-center gap-2 px-6 py-4">
        {icon}
        <span className="text-base font-semibold text-zinc-100">
          {subtitle || title}
        </span>
      </div>
    );
  }

  if (variant === "compact") {
    return (
      <div className="flex w-full items-center justify-between">
        <div className="flex items-center gap-3">
          {icon}
          <span className="text-sm font-medium text-zinc-100">{title}</span>
        </div>
        {progress !== undefined && (
          <div className={`text-sm font-medium ${getProgressColor(progress)}`}>
            {progress}%
          </div>
        )}
      </div>
    );
  }

  // Default variant
  return (
    <div className="flex items-start justify-between gap-2">
      <div className="flex-1">
        <h3 className="text-base font-semibold text-zinc-100">{title}</h3>
      </div>
      {showExpandToggle && (
        <button
          onClick={onToggleExpand}
          className="rounded-lg p-2 transition-colors hover:bg-zinc-800"
        >
          <ArrowRight01Icon
            className={`h-4 w-4 text-zinc-500 transition-transform ${
              isExpanded ? "rotate-90" : ""
            }`}
          />
        </button>
      )}
    </div>
  );
}

function GoalCardContent({
  description,
  progress = 0,
  metadata,
  expandedContent,
  isExpanded = false,
  variant = "default",
  showProgress = true,
  title,
}: GoalCardContentProps) {
  const getProgressColor = (progress: number) => {
    if (progress >= 90) return "text-green-500";
    if (progress >= 75) return "text-blue-500";
    if (progress >= 50) return "text-yellow-500";
    if (progress >= 25) return "text-orange-500";
    return "text-red-500";
  };

  if (variant === "create") {
    return (
      <div className="space-y-4 p-6">
        {title && (
          <div>
            <h3 className="mb-1 text-lg font-semibold text-zinc-100">
              {title}
            </h3>
          </div>
        )}
        {description && (
          <div>
            <p className="text-sm leading-relaxed text-zinc-400">
              {description}
            </p>
          </div>
        )}
      </div>
    );
  }

  if (variant === "compact") {
    return null; // Compact variant doesn't show content, everything is in header
  }

  // Default variant
  return (
    <div className="space-y-4">
      {/* Progress Bar */}
      {showProgress && (
        <div className="mt-3 mb-4">
          <div className="mb-2 flex items-center justify-between text-sm">
            <span className="font-medium text-zinc-400">Progress</span>
            <span className={`font-semibold ${getProgressColor(progress)}`}>
              {progress}%
            </span>
          </div>
          <div className="h-2 w-full rounded-full bg-zinc-700">
            <div
              className={`h-2 rounded-full transition-all duration-300 ${
                progress >= 90
                  ? "bg-green-500"
                  : progress >= 75
                    ? "bg-blue-500"
                    : progress >= 50
                      ? "bg-yellow-500"
                      : progress >= 25
                        ? "bg-orange-500"
                        : "bg-red-500"
              }`}
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      )}

      {/* Metadata */}
      {metadata && <div className="mb-3">{metadata}</div>}

      {/* Expanded Content */}
      {isExpanded && expandedContent && (
        <div className="space-y-4 border-t border-zinc-700 pt-4">
          {description && (
            <div>
              <p className="text-sm leading-relaxed text-zinc-400">
                {description}
              </p>
            </div>
          )}
          {expandedContent}
        </div>
      )}
    </div>
  );
}

function GoalCardActions({
  variant = "default",
  onViewGoal,
  onViewTasks,
  showViewTasks = false,
  className = "",
}: GoalCardActionsProps) {
  if (variant === "create") {
    return (
      <div className={`pt-2 ${className}`}>
        <button
          onClick={onViewGoal}
          className="w-full rounded-xl bg-primary px-4 py-3 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
        >
          View Goal
        </button>
      </div>
    );
  }

  if (variant === "compact") {
    return null; // Compact variant handles actions in the container click
  }

  // Default variant
  return (
    <div className={`flex gap-3 pt-2 ${className}`}>
      <button
        onClick={onViewGoal}
        className="flex-1 rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
      >
        View Goal
      </button>
      {showViewTasks && (
        <button
          onClick={onViewTasks}
          className="flex-1 rounded-lg bg-zinc-700 px-4 py-2.5 text-sm font-medium text-zinc-300 transition-colors hover:bg-zinc-600"
        >
          View Tasks
        </button>
      )}
    </div>
  );
}

// Reusable Goal Card Component
export function GoalCard({
  goal,
  variant = "default",
  showActions = true,
  showExpandToggle = true,
  isExpanded = false,
  onToggleExpand,
  onViewGoal,
  onViewTasks,
}: GoalCardProps) {
  const hasRoadmap = goal.roadmap?.nodes && goal.roadmap.nodes.length > 0;

  const roadmapTasks =
    goal.roadmap?.nodes?.length && goal.roadmap.nodes.length > 0
      ? goal.roadmap.nodes.filter(
          (node) => node.data.type !== "start" && node.data.type !== "end",
        )
      : [];
  const completedTasks = roadmapTasks.filter((node) => node.data.isComplete);
  const progress =
    roadmapTasks.length > 0
      ? Math.round((completedTasks.length / roadmapTasks.length) * 100)
      : goal.progress || 0;

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return format(date, "MMM d, yyyy");
  };

  const getProgressColor = (progress: number) => {
    if (progress >= 90) return "text-green-500";
    if (progress >= 75) return "text-blue-500";
    if (progress >= 50) return "text-yellow-500";
    if (progress >= 25) return "text-orange-500";
    return "text-red-500";
  };

  const getProgressBgColor = (progress: number) => {
    if (progress >= 90) return "bg-green-500/10";
    if (progress >= 75) return "bg-blue-500/10";
    if (progress >= 50) return "bg-yellow-500/10";
    if (progress >= 25) return "bg-orange-500/10";
    return "bg-red-500/10";
  };

  // Metadata component
  const metadata = (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      {hasRoadmap && (
        <span
          className={`flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium ${getProgressBgColor(progress)} ${getProgressColor(progress)}`}
        >
          <UserGroupIcon className="h-3 w-3" />
          {completedTasks.length}/{roadmapTasks.length} tasks
        </span>
      )}

      {goal.created_at && (
        <span className="flex items-center gap-1 rounded-full bg-zinc-800 px-3 py-1 text-xs font-medium text-zinc-400">
          <CalendarIcon className="h-3 w-3" />
          {formatDate(goal.created_at)}
        </span>
      )}

      {goal.todo_project_id && (
        <span className="flex items-center gap-1 rounded-full bg-zinc-800 px-3 py-1 text-xs font-medium text-zinc-400">
          <Award01Icon className="h-3 w-3" />
          Linked to Todos
        </span>
      )}
    </div>
  );

  // Expanded content for default variant
  const expandedContent = hasRoadmap && roadmapTasks.length > 0 && (
    <div>
      <p className="mb-3 text-sm font-medium text-zinc-300">Roadmap Tasks</p>
      <div className="space-y-2">
        {roadmapTasks.map((node) => (
          <div key={node.id} className="flex items-center gap-3 py-1">
            <div
              className={`flex h-4 w-4 items-center justify-center rounded-full border-2 ${
                node.data.isComplete
                  ? "border-green-500 bg-green-500"
                  : "border-zinc-600"
              }`}
            >
              {node.data.isComplete && (
                <CheckmarkCircle02Icon className="h-2.5 w-2.5 text-white" />
              )}
            </div>
            <span
              className={`text-sm ${
                node.data.isComplete
                  ? "text-zinc-500 line-through"
                  : "text-zinc-300"
              }`}
            >
              {node.data.title || node.data.label || "Untitled Task"}
            </span>
          </div>
        ))}
      </div>
    </div>
  );

  // Compact variant
  if (variant === "compact") {
    return (
      <GoalCardContainer
        variant="compact"
        onClick={() => onViewGoal?.(goal.id)}
      >
        <GoalCardHeader
          title={goal.title}
          variant="compact"
          icon={<Target02Icon className="h-4 w-4 text-primary" />}
          progress={progress}
        />
      </GoalCardContainer>
    );
  }

  // Create variant
  if (variant === "create") {
    return (
      <GoalCardContainer variant="create">
        <GoalCardHeader
          title={goal.title}
          variant="create"
          icon={<Target02Icon className="h-5 w-5 text-primary" />}
          subtitle="Goal Created"
        />
        <GoalCardContent
          description={goal.description}
          variant="create"
          title={goal.title}
        />
        {showActions && (
          <GoalCardActions
            variant="create"
            onViewGoal={() => onViewGoal?.(goal.id)}
            className="px-6 pb-6"
          />
        )}
      </GoalCardContainer>
    );
  }

  // Default variant
  return (
    <GoalCardContainer variant="default">
      <div className="flex items-start gap-3">
        <div className="flex-1 space-y-4">
          <GoalCardHeader
            title={goal.title}
            variant="default"
            showExpandToggle={
              showExpandToggle && (!!goal.description || hasRoadmap)
            }
            isExpanded={isExpanded}
            onToggleExpand={() => onToggleExpand?.(goal.id)}
          />

          <GoalCardContent
            description={goal.description}
            progress={progress}
            metadata={metadata}
            expandedContent={expandedContent}
            isExpanded={isExpanded}
            variant="default"
            showProgress={true}
          />

          {showActions && (
            <GoalCardActions
              variant="default"
              onViewGoal={() => onViewGoal?.(goal.id)}
              onViewTasks={() =>
                goal.todo_project_id && onViewTasks?.(goal.todo_project_id)
              }
              showViewTasks={hasRoadmap && !!goal.todo_project_id}
            />
          )}
        </div>
      </div>
    </GoalCardContainer>
  );
}

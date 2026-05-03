import type {
  GoalDataMessageType as GoalData,
  GoalItem,
  GoalRoadmap,
  GoalRoadmapNode,
} from "@gaia/shared";
import { useState } from "react";
import { Pressable, View } from "react-native";
import {
  AppIcon,
  ArrowRight01Icon,
  Calendar03Icon,
  Cancel01Icon,
  ChartLineData01Icon,
  CheckmarkCircle02Icon,
  Clock01Icon,
  Target02Icon,
  UserGroupIcon,
  ZapIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  ToolCardHeader,
  ToolCardInner,
  ToolCardShell,
} from "@/features/chat/tool-data/primitives";

export type { GoalData, GoalItem, GoalRoadmap, GoalRoadmapNode };

function getProgressBarColor(pct: number): string {
  if (pct >= 90) return "bg-emerald-500";
  if (pct >= 75) return "bg-blue-500";
  if (pct >= 50) return "bg-amber-500";
  if (pct >= 25) return "bg-orange-500";
  return "bg-red-500";
}

function getProgressTextColor(pct: number): string {
  if (pct >= 90) return "text-emerald-500";
  if (pct >= 75) return "text-blue-500";
  if (pct >= 50) return "text-amber-500";
  if (pct >= 25) return "text-orange-500";
  return "text-red-500";
}

function getProgressBgColor(pct: number): string {
  if (pct >= 90) return "bg-emerald-500/10";
  if (pct >= 75) return "bg-blue-500/10";
  if (pct >= 50) return "bg-amber-500/10";
  if (pct >= 25) return "bg-orange-500/10";
  return "bg-red-500/10";
}

function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function computeProgress(goal: GoalItem): number {
  const roadmapTasks =
    goal.roadmap?.nodes?.filter(
      (n) => n.data.type !== "start" && n.data.type !== "end",
    ) ?? [];

  if (roadmapTasks.length > 0) {
    const completedCount = roadmapTasks.filter((n) => n.data.isComplete).length;
    return Math.round((completedCount / roadmapTasks.length) * 100);
  }

  return goal.progress ?? 0;
}

function GoalItemCard({ goal }: { goal: GoalItem }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const progress = computeProgress(goal);
  const roadmapTasks =
    goal.roadmap?.nodes?.filter(
      (n) => n.data.type !== "start" && n.data.type !== "end",
    ) ?? [];
  const completedTasks = roadmapTasks.filter((n) => n.data.isComplete).length;
  const hasRoadmap = roadmapTasks.length > 0;
  const hasExpandable = !!goal.description || hasRoadmap;

  const metaIconColor =
    progress >= 90
      ? "#10b981"
      : progress >= 75
        ? "#3b82f6"
        : progress >= 50
          ? "#f59e0b"
          : progress >= 25
            ? "#f97316"
            : "#ef4444";

  return (
    <ToolCardInner>
      {/* Title row with expand toggle */}
      <View className="flex-row items-start justify-between gap-2">
        <View className="flex-1">
          <Text className="text-base font-semibold text-zinc-100">
            {goal.title}
          </Text>
        </View>
        {hasExpandable && (
          <Pressable
            className="rounded-lg p-1 -mr-1"
            onPress={() => setIsExpanded((prev) => !prev)}
            hitSlop={8}
          >
            <View
              style={{
                transform: [{ rotate: isExpanded ? "90deg" : "0deg" }],
              }}
            >
              <AppIcon icon={ArrowRight01Icon} size={16} color="#71717a" />
            </View>
          </Pressable>
        )}
      </View>

      {/* Progress bar */}
      <View className="mt-3 mb-3">
        <View className="flex-row items-center justify-between mb-2">
          <Text className="text-sm font-medium text-zinc-400">Progress</Text>
          <Text
            className={`text-sm font-semibold ${getProgressTextColor(progress)}`}
          >
            {progress}%
          </Text>
        </View>
        <View className="h-2 w-full rounded-full bg-zinc-700 overflow-hidden">
          <View
            className={`h-2 rounded-full ${getProgressBarColor(progress)}`}
            style={{ width: `${Math.min(100, Math.max(0, progress))}%` }}
          />
        </View>
      </View>

      {/* Metadata pills */}
      <View className="flex-row flex-wrap gap-2 mb-3">
        {hasRoadmap && (
          <View
            className={`flex-row items-center gap-1 rounded-full px-3 py-1 ${getProgressBgColor(progress)}`}
          >
            <AppIcon icon={UserGroupIcon} size={12} color={metaIconColor} />
            <Text
              className={`text-xs font-medium ${getProgressTextColor(progress)}`}
            >
              {completedTasks}/{roadmapTasks.length} tasks
            </Text>
          </View>
        )}

        {goal.created_at && (
          <View className="flex-row items-center gap-1 rounded-full bg-zinc-800 px-3 py-1">
            <AppIcon icon={Calendar03Icon} size={12} color="#71717a" />
            <Text className="text-xs font-medium text-zinc-400">
              {formatDate(goal.created_at)}
            </Text>
          </View>
        )}

        {goal.todo_project_id && (
          <View className="flex-row items-center gap-1 rounded-full bg-zinc-800 px-3 py-1">
            <AppIcon icon={Target02Icon} size={12} color="#71717a" />
            <Text className="text-xs font-medium text-zinc-400">
              Linked to Todos
            </Text>
          </View>
        )}
      </View>

      {/* Expanded: description + roadmap tasks */}
      {isExpanded && (
        <View className="pt-4 mb-3 gap-4">
          <View className="h-px bg-zinc-700/50 -mt-4 mb-0" />
          {goal.description && (
            <Text className="text-sm leading-relaxed text-zinc-400">
              {goal.description}
            </Text>
          )}
          {hasRoadmap && (
            <View>
              <Text className="text-sm font-medium text-zinc-200 mb-3">
                Roadmap Tasks
              </Text>
              <View className="gap-2">
                {roadmapTasks.map((node) => (
                  <View
                    key={node.id}
                    className="flex-row items-center gap-3 py-1"
                  >
                    <View
                      className={`h-4 w-4 items-center justify-center rounded-full border-2 ${node.data.isComplete ? "border-green-500 bg-green-500" : "border-zinc-600"}`}
                    >
                      {node.data.isComplete && (
                        <AppIcon
                          icon={CheckmarkCircle02Icon}
                          size={10}
                          color="#fff"
                        />
                      )}
                    </View>
                    <Text
                      className={`text-sm ${node.data.isComplete ? "text-zinc-500 line-through" : "text-zinc-200"}`}
                    >
                      {node.data.title || node.data.label || "Untitled Task"}
                    </Text>
                  </View>
                ))}
              </View>
            </View>
          )}
        </View>
      )}

      {/* Action buttons — display-only (no navigation in mobile tool cards) */}
      <View className="flex-row gap-3 pt-2">
        <View
          className="flex-1 rounded-lg py-1.5 items-center justify-center"
          style={{ backgroundColor: "rgba(0,187,255,0.12)" }}
        >
          <Text className="text-xs font-semibold text-primary">View Goal</Text>
        </View>
        {hasRoadmap && goal.todo_project_id && (
          <View
            className="flex-1 rounded-lg py-1.5 items-center justify-center"
            style={{ backgroundColor: "rgba(63,63,70,0.5)" }}
          >
            <Text className="text-xs font-semibold text-zinc-400">
              View Tasks
            </Text>
          </View>
        )}
      </View>
    </ToolCardInner>
  );
}

function SingleGoalCreateCard({ goal }: { goal: GoalItem }) {
  return (
    <View className="mx-4 my-1 rounded-3xl bg-zinc-800 overflow-hidden">
      {/* Header */}
      <View className="flex-row items-center gap-2 px-6 py-4">
        <AppIcon icon={Target02Icon} size={20} color="#a855f7" />
        <Text className="text-base font-semibold text-zinc-100">
          Goal Created
        </Text>
      </View>

      {/* Content */}
      <View className="px-6 pb-2 gap-4">
        <View>
          <Text className="text-lg font-semibold text-zinc-100 mb-1">
            {goal.title}
          </Text>
          {goal.description && (
            <Text className="text-sm leading-relaxed text-zinc-400">
              {goal.description}
            </Text>
          )}
        </View>
      </View>

      {/* Action — display-only */}
      <View className="px-6 pb-6 pt-2">
        <View
          className="w-full rounded-xl py-2.5 items-center justify-center"
          style={{ backgroundColor: "rgba(0,187,255,0.15)" }}
        >
          <Text className="text-sm font-semibold text-primary">View Goal</Text>
        </View>
      </View>
    </View>
  );
}

function StatsCard({ data }: { data: GoalData }) {
  const { stats } = data;
  if (!stats) return null;

  return (
    <ToolCardShell>
      <ToolCardHeader
        icon={Target02Icon}
        iconColor="#a855f7"
        title="Goal Progress Overview"
      />
      <View className="flex-row flex-wrap gap-2">
        <View className="rounded-xl bg-zinc-900 p-3 items-center flex-1 min-w-[30%]">
          <Text className="text-xl font-semibold text-zinc-100">
            {stats.total_goals}
          </Text>
          <Text className="text-xs text-zinc-500">Total Goals</Text>
        </View>
        <View className="rounded-xl bg-zinc-900 p-3 items-center flex-1 min-w-[30%]">
          <Text className="text-xl font-semibold text-blue-500">
            {stats.goals_with_roadmaps}
          </Text>
          <Text className="text-xs text-zinc-500">With Roadmaps</Text>
        </View>
        <View className="rounded-xl bg-zinc-900 p-3 items-center flex-1 min-w-[30%]">
          <Text className="text-xl font-semibold text-green-500">
            {stats.overall_completion_rate}%
          </Text>
          <Text className="text-xs text-zinc-500">Complete</Text>
        </View>
        <View className="rounded-xl bg-zinc-900 p-3 items-center flex-1 min-w-[30%]">
          <Text className="text-xl font-semibold text-blue-500">
            {stats.total_tasks}
          </Text>
          <Text className="text-xs text-zinc-500">Total Tasks</Text>
        </View>
        <View className="rounded-xl bg-zinc-900 p-3 items-center flex-1 min-w-[30%]">
          <Text className="text-xl font-semibold text-green-500">
            {stats.completed_tasks}
          </Text>
          <Text className="text-xs text-zinc-500">Done Tasks</Text>
        </View>
        <View className="rounded-xl bg-zinc-900 p-3 items-center flex-1 min-w-[30%]">
          <Text className="text-xl font-semibold text-orange-500">
            {stats.active_goals_count}
          </Text>
          <Text className="text-xs text-zinc-500">Active</Text>
        </View>
      </View>

      {stats.active_goals && stats.active_goals.length > 0 && (
        <View className="mt-4">
          <Text className="text-xs font-medium text-zinc-500 mb-2">
            Top Active Goals
          </Text>
          <View className="gap-2">
            {stats.active_goals.map((goal) => (
              <View
                key={goal.id}
                className="flex-row items-center justify-between rounded-xl bg-zinc-900 p-3"
              >
                <View className="flex-row items-center gap-3 flex-1">
                  <AppIcon icon={Target02Icon} size={16} color="#a855f7" />
                  <Text
                    className="text-sm font-medium text-zinc-100 flex-1"
                    numberOfLines={1}
                  >
                    {goal.title}
                  </Text>
                </View>
                <Text
                  className={`text-sm font-medium ${getProgressTextColor(goal.progress ?? 0)}`}
                >
                  {goal.progress ?? 0}%
                </Text>
              </View>
            ))}
          </View>
        </View>
      )}
    </ToolCardShell>
  );
}

// Loading-action icon map — mirrors web GoalSection
const LOADING_ACTION_ICONS: Record<
  string,
  { icon: typeof ZapIcon; color: string }
> = {
  creating: { icon: ZapIcon, color: "#3b82f6" },
  fetching: { icon: Clock01Icon, color: "#3b82f6" },
  deleting: { icon: Clock01Icon, color: "#ef4444" },
  updating_progress: { icon: ChartLineData01Icon, color: "#22c55e" },
  generating_roadmap: { icon: UserGroupIcon, color: "#00bbff" },
};

export function GoalCard({ data }: { data: GoalData }) {
  const action = data.action ?? "list";

  // Stats view
  if (action === "stats" && data.stats) {
    return <StatsCard data={data} />;
  }

  // Loading / progress message states (creating, fetching, deleting,
  // updating_progress, generating_roadmap) — mirrors web GoalSection
  const loadingMeta = LOADING_ACTION_ICONS[action];
  if (loadingMeta && data.message) {
    return (
      <ToolCardShell>
        <View className="flex-row items-center gap-2">
          <AppIcon
            icon={loadingMeta.icon}
            size={16}
            color={loadingMeta.color}
          />
          <Text className="text-sm text-zinc-100 flex-1">{data.message}</Text>
        </View>
      </ToolCardShell>
    );
  }

  // Roadmap needed — message + "Generate Roadmap" display button
  if (action === "roadmap_needed" && data.message) {
    return (
      <ToolCardShell>
        <View className="flex-row items-center gap-2 mb-3">
          <AppIcon icon={UserGroupIcon} size={16} color="#00bbff" />
          <Text className="text-sm text-zinc-200 flex-1">{data.message}</Text>
        </View>
        <View
          className="w-full rounded-xl py-2.5 items-center justify-center"
          style={{ backgroundColor: "rgba(0,187,255,0.15)" }}
        >
          <Text className="text-sm font-semibold text-primary">
            Generate Roadmap
          </Text>
        </View>
      </ToolCardShell>
    );
  }

  // Single goal create — use rich card
  if (action === "create" && data.goals && data.goals.length === 1) {
    return <SingleGoalCreateCard goal={data.goals[0]} />;
  }

  // Goals list
  if (data.goals && data.goals.length > 0) {
    const headerLabel =
      action === "search"
        ? "Search Results"
        : action === "roadmap_generated"
          ? "Goal with Roadmap"
          : action === "node_updated"
            ? "Updated Progress"
            : action === "create"
              ? "New Goals"
              : action === "update"
                ? "Updated Goals"
                : action === "delete"
                  ? "Deleted Goals"
                  : "Your Goals";

    return (
      <ToolCardShell>
        <ToolCardHeader
          icon={Target02Icon}
          iconColor="#a855f7"
          title={headerLabel}
          count={data.goals.length}
        />
        <View className="gap-3">
          {data.goals.map((goal) => (
            <GoalItemCard key={goal.id} goal={goal} />
          ))}
        </View>
        {data.message && (
          <Text className="text-xs text-zinc-500 mt-3">{data.message}</Text>
        )}
      </ToolCardShell>
    );
  }

  // Empty state for list action — mirrors web
  if (action === "list" && (!data.goals || data.goals.length === 0)) {
    return (
      <ToolCardShell>
        <View className="items-center py-4">
          <AppIcon icon={Target02Icon} size={32} color="#52525b" />
          <Text className="mt-2 text-sm text-zinc-200">No goals found</Text>
          {data.message && (
            <Text className="text-xs text-zinc-500 mt-1">{data.message}</Text>
          )}
        </View>
      </ToolCardShell>
    );
  }

  // Action message with no goals (delete/success confirmation)
  if (data.message) {
    const isDelete = action === "delete";
    return (
      <ToolCardShell>
        <View className="flex-row items-center gap-2">
          <AppIcon
            icon={isDelete ? Cancel01Icon : CheckmarkCircle02Icon}
            size={16}
            color={isDelete ? "#ef4444" : "#22c55e"}
          />
          <Text className="text-sm text-zinc-100 flex-1">{data.message}</Text>
        </View>
      </ToolCardShell>
    );
  }

  return null;
}

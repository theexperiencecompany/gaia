import { useState } from "react";
import { Pressable, View } from "react-native";
import {
  AppIcon,
  ArrowRight01Icon,
  BarChartIcon,
  Calendar03Icon,
  ChartLineData01Icon,
  CheckListIcon,
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
} from "../primitives";

export type GoalAction =
  | "create"
  | "list"
  | "get"
  | "delete"
  | "search"
  | "stats"
  | "creating"
  | "fetching"
  | "deleting"
  | "updating_progress"
  | "generating_roadmap"
  | "roadmap_generated"
  | "roadmap_needed"
  | "node_updated"
  | "update"
  | "error";

export interface GoalRoadmapNode {
  id: string;
  data: {
    id?: string;
    title?: string;
    label?: string;
    isComplete?: boolean;
    type?: string;
  };
}

export interface GoalRoadmap {
  nodes?: GoalRoadmapNode[];
}

export interface GoalItem {
  id: string;
  title: string;
  description?: string;
  progress?: number;
  created_at?: string;
  todo_project_id?: string;
  roadmap?: GoalRoadmap;
}

export interface GoalStats {
  total_goals: number;
  goals_with_roadmaps: number;
  total_tasks: number;
  completed_tasks: number;
  overall_completion_rate: number;
  active_goals?: Array<{
    id: string;
    title: string;
    progress: number;
  }>;
  active_goals_count: number;
}

export interface GoalData {
  goals?: GoalItem[];
  stats?: GoalStats;
  action?: GoalAction;
  message?: string;
  goal_id?: string;
  deleted_goal_id?: string;
  error?: string;
}

// ---- Color helpers (mirror web) ----

function getProgressTextColor(pct: number): string {
  if (pct >= 90) return "text-green-500";
  if (pct >= 75) return "text-blue-500";
  if (pct >= 50) return "text-yellow-500";
  if (pct >= 25) return "text-orange-500";
  return "text-red-500";
}

function getProgressBarColor(pct: number): string {
  if (pct >= 90) return "bg-green-500";
  if (pct >= 75) return "bg-blue-500";
  if (pct >= 50) return "bg-yellow-500";
  if (pct >= 25) return "bg-orange-500";
  return "bg-red-500";
}

function getProgressBgColor(pct: number): string {
  // Web uses bg-*-500/10 soft tint pills for task ratio chips
  if (pct >= 90) return "bg-green-500/10";
  if (pct >= 75) return "bg-blue-500/10";
  if (pct >= 50) return "bg-yellow-500/10";
  if (pct >= 25) return "bg-orange-500/10";
  return "bg-red-500/10";
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function computeGoalMetrics(goal: GoalItem) {
  const allNodes = goal.roadmap?.nodes ?? [];
  const roadmapTasks = allNodes.filter(
    (n) => n.data.type !== "start" && n.data.type !== "end",
  );
  const completedTasks = roadmapTasks.filter((n) => n.data.isComplete);
  const progress =
    roadmapTasks.length > 0
      ? Math.round((completedTasks.length / roadmapTasks.length) * 100)
      : (goal.progress ?? 0);
  const hasRoadmap = roadmapTasks.length > 0;
  return {
    roadmapTasks,
    completedTasks,
    progress,
    hasRoadmap,
  };
}

// ---- Pills (meta row) ----

function MetaPill({
  icon,
  iconColor,
  label,
  bgClass = "bg-zinc-700",
  textClass = "text-zinc-300",
}: {
  icon: React.ComponentType<{ size?: number; color?: string }>;
  iconColor?: string;
  label: string;
  bgClass?: string;
  textClass?: string;
}) {
  return (
    <View
      className={`flex-row items-center gap-1 rounded-full px-3 py-1 ${bgClass}`}
    >
      <AppIcon icon={icon} size={12} color={iconColor ?? "#d4d4d8"} />
      <Text className={`text-xs font-medium ${textClass}`}>{label}</Text>
    </View>
  );
}

// ---- Roadmap checklist row ----

function RoadmapItem({ node }: { node: GoalRoadmapNode }) {
  const isComplete = !!node.data.isComplete;
  const title =
    node.data.title || node.data.label || "Untitled Task";

  return (
    <View className="flex-row items-center gap-3 py-1">
      <View
        className={`h-4 w-4 items-center justify-center rounded-full ${isComplete ? "bg-green-500" : "bg-zinc-700"}`}
      >
        {isComplete ? (
          <AppIcon icon={CheckmarkCircle02Icon} size={10} color="#ffffff" />
        ) : null}
      </View>
      <Text
        className={`text-sm flex-1 ${isComplete ? "text-zinc-500 line-through" : "text-zinc-300"}`}
      >
        {title}
      </Text>
    </View>
  );
}

// ---- Default variant row used inside list ----

function GoalItemCard({ goal }: { goal: GoalItem }) {
  const { roadmapTasks, completedTasks, progress, hasRoadmap } =
    computeGoalMetrics(goal);

  const canExpand = !!goal.description || hasRoadmap;
  const [isExpanded, setIsExpanded] = useState(false);

  return (
    <ToolCardInner className="mb-3">
      {/* Title + expand toggle */}
      <View className="flex-row items-start justify-between gap-2">
        <Text
          className="text-base font-semibold text-zinc-100 flex-1"
          numberOfLines={2}
        >
          {goal.title}
        </Text>
        {canExpand ? (
          <Pressable
            onPress={() => setIsExpanded((v) => !v)}
            className="rounded-lg p-1.5"
            hitSlop={6}
          >
            <View
              style={{
                transform: [{ rotate: isExpanded ? "90deg" : "0deg" }],
              }}
            >
              <AppIcon icon={ArrowRight01Icon} size={16} color="#71717a" />
            </View>
          </Pressable>
        ) : null}
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
            style={{
              width: `${Math.min(100, Math.max(0, progress))}%`,
            }}
          />
        </View>
      </View>

      {/* Metadata pills */}
      <View className="flex-row flex-wrap items-center gap-2">
        {hasRoadmap ? (
          <View
            className={`flex-row items-center gap-1 rounded-full px-3 py-1 ${getProgressBgColor(progress)}`}
          >
            <AppIcon
              icon={UserGroupIcon}
              size={12}
              color={progressHex(progress)}
            />
            <Text
              className={`text-xs font-medium ${getProgressTextColor(progress)}`}
            >
              {completedTasks.length}/{roadmapTasks.length} tasks
            </Text>
          </View>
        ) : null}

        {goal.created_at ? (
          <MetaPill
            icon={Calendar03Icon}
            iconColor="#a1a1aa"
            label={formatDate(goal.created_at)}
            bgClass="bg-zinc-700"
            textClass="text-zinc-300"
          />
        ) : null}

        {goal.todo_project_id ? (
          <MetaPill
            icon={CheckListIcon}
            iconColor="#a1a1aa"
            label="Linked to Todos"
            bgClass="bg-zinc-700"
            textClass="text-zinc-300"
          />
        ) : null}
      </View>

      {/* Expanded — description + roadmap */}
      {isExpanded && canExpand ? (
        <View className="mt-4 pt-4">
          {goal.description ? (
            <Text className="text-sm leading-relaxed text-zinc-400 mb-3">
              {goal.description}
            </Text>
          ) : null}
          {hasRoadmap ? (
            <View>
              <Text className="mb-3 text-sm font-medium text-zinc-300">
                Roadmap Tasks
              </Text>
              <View>
                {roadmapTasks.map((node) => (
                  <RoadmapItem key={node.id} node={node} />
                ))}
              </View>
            </View>
          ) : null}
        </View>
      ) : null}
    </ToolCardInner>
  );
}

function progressHex(pct: number): string {
  if (pct >= 90) return "#22c55e";
  if (pct >= 75) return "#3b82f6";
  if (pct >= 50) return "#eab308";
  if (pct >= 25) return "#f97316";
  return "#ef4444";
}

// ---- Create variant (single goal) ----

function SingleGoalCreateCard({ goal }: { goal: GoalItem }) {
  const { progress } = computeGoalMetrics(goal);

  return (
    <ToolCardShell>
      {/* Header */}
      <View className="flex-row items-center gap-2 mb-3">
        <AppIcon icon={Target02Icon} size={18} color="#00bbff" />
        <Text className="text-base font-semibold text-zinc-100">
          Goal Created
        </Text>
      </View>

      {/* Content */}
      <Text className="text-lg font-semibold text-zinc-100 mb-1">
        {goal.title}
      </Text>
      {goal.description ? (
        <Text className="text-sm leading-relaxed text-zinc-400 mb-3">
          {goal.description}
        </Text>
      ) : null}

      {/* Progress */}
      <View className="mb-3">
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

      {goal.created_at ? (
        <Text className="text-xs text-zinc-500 mt-1 mb-3">
          Created {formatDate(goal.created_at)}
        </Text>
      ) : null}
    </ToolCardShell>
  );
}

// ---- Compact (used inside stats → active goals) ----

function CompactGoalRow({
  goal,
}: {
  goal: { id: string; title: string; progress: number };
}) {
  return (
    <ToolCardInner className="mb-2">
      <View className="flex-row items-center justify-between">
        <View className="flex-row items-center gap-3 flex-1">
          <AppIcon icon={Target02Icon} size={16} color="#00bbff" />
          <Text
            className="text-sm font-medium text-zinc-100 flex-1"
            numberOfLines={1}
          >
            {goal.title}
          </Text>
        </View>
        <Text
          className={`text-sm font-medium ${getProgressTextColor(goal.progress)}`}
        >
          {goal.progress}%
        </Text>
      </View>
    </ToolCardInner>
  );
}

// ---- Stats view ----

function StatBox({
  value,
  label,
  colorClass,
}: {
  value: number | string;
  label: string;
  colorClass: string;
}) {
  return (
    <View className="flex-1 rounded-2xl bg-zinc-900 p-3 items-center">
      <Text className={`text-xl font-semibold ${colorClass}`}>{value}</Text>
      <Text className="text-xs text-zinc-500 mt-0.5">{label}</Text>
    </View>
  );
}

function StatsView({ data }: { data: GoalData }) {
  const stats = data.stats;
  if (!stats) return null;

  return (
    <ToolCardShell>
      <View className="flex-row items-center gap-2 mb-3">
        <AppIcon icon={BarChartIcon} size={16} color="#00bbff" />
        <Text className="text-sm text-zinc-100">Goal Progress Overview</Text>
      </View>

      {/* 2 rows of 3 stat boxes */}
      <View className="flex-row gap-2 mb-2">
        <StatBox
          value={stats.total_goals}
          label="Total Goals"
          colorClass="text-zinc-100"
        />
        <StatBox
          value={stats.goals_with_roadmaps}
          label="With Roadmaps"
          colorClass="text-blue-500"
        />
        <StatBox
          value={`${stats.overall_completion_rate}%`}
          label="Complete"
          colorClass="text-green-500"
        />
      </View>
      <View className="flex-row gap-2">
        <StatBox
          value={stats.total_tasks}
          label="Total Tasks"
          colorClass="text-blue-500"
        />
        <StatBox
          value={stats.completed_tasks}
          label="Done Tasks"
          colorClass="text-green-500"
        />
        <StatBox
          value={stats.active_goals_count}
          label="Active"
          colorClass="text-orange-500"
        />
      </View>

      {stats.active_goals && stats.active_goals.length > 0 ? (
        <View className="mt-4">
          <Text className="mb-2 text-xs font-medium text-zinc-500">
            Top Active Goals
          </Text>
          <View>
            {stats.active_goals.map((g) => (
              <CompactGoalRow key={g.id} goal={g} />
            ))}
          </View>
        </View>
      ) : null}
    </ToolCardShell>
  );
}

// ---- Loading / progress icon map (mirrors web GoalSection) ----

const LOADING_ACTION_META: Record<
  string,
  {
    icon: typeof ZapIcon;
    color: string;
  }
> = {
  creating: { icon: ZapIcon, color: "#3b82f6" },
  fetching: { icon: Clock01Icon, color: "#3b82f6" },
  deleting: { icon: Clock01Icon, color: "#ef4444" },
  updating_progress: { icon: ChartLineData01Icon, color: "#22c55e" },
  generating_roadmap: { icon: UserGroupIcon, color: "#00bbff" },
};

// ---- Main component ----

export function GoalCard({ data }: { data: GoalData }) {
  const action = data.action ?? "list";

  // Error state
  if (data.error) {
    return (
      <ToolCardShell>
        <View className="flex-row items-center gap-2">
          <AppIcon icon={CheckmarkCircle02Icon} size={16} color="#ef4444" />
          <Text className="text-sm text-red-400 flex-1">{data.error}</Text>
        </View>
      </ToolCardShell>
    );
  }

  // Stats
  if (action === "stats" && data.stats) {
    return <StatsView data={data} />;
  }

  // Loading / progress message states
  const loadingMeta = LOADING_ACTION_META[action];
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
          <Text className="text-sm text-zinc-300 flex-1">{data.message}</Text>
        </View>
        <View className="w-full rounded-xl py-2.5 items-center justify-center bg-primary">
          <Text className="text-sm font-semibold text-primary-foreground">
            Generate Roadmap
          </Text>
        </View>
      </ToolCardShell>
    );
  }

  // Create with single goal → rich create card
  if (action === "create" && data.goals && data.goals.length === 1) {
    return <SingleGoalCreateCard goal={data.goals[0]} />;
  }

  // Goals list
  if (data.goals && data.goals.length > 0) {
    const headerTitle =
      action === "search"
        ? "Search Results"
        : action === "roadmap_generated"
          ? "Goal with Roadmap"
          : action === "node_updated"
            ? "Updated Progress"
            : action === "update"
              ? "Updated Goals"
              : action === "delete"
                ? "Deleted Goals"
                : "Your Goals";

    const count = data.goals.length;

    return (
      <ToolCardShell>
        <ToolCardHeader
          icon={Target02Icon}
          iconColor="#00bbff"
          title={headerTitle}
          trailing={
            <Text className="text-xs text-zinc-500">
              {count} {count === 1 ? "goal" : "goals"}
            </Text>
          }
        />
        <View>
          {data.goals.map((goal) => (
            <GoalItemCard key={goal.id} goal={goal} />
          ))}
        </View>
        {data.message ? (
          <Text className="text-xs text-zinc-500 mt-1">{data.message}</Text>
        ) : null}
      </ToolCardShell>
    );
  }

  // Empty state for list action
  if (action === "list" && (!data.goals || data.goals.length === 0)) {
    return (
      <ToolCardShell>
        <View className="items-center py-4">
          <AppIcon icon={Target02Icon} size={32} color="#52525b" />
          <Text className="mt-2 text-sm text-zinc-300">No goals found</Text>
          {data.message ? (
            <Text className="text-xs text-zinc-500 mt-1">{data.message}</Text>
          ) : null}
        </View>
      </ToolCardShell>
    );
  }

  // Success / action message with no goals / stats
  if (data.message && !data.goals && !data.stats) {
    const isDelete = action === "delete";
    const isSuccess =
      action === "create" ||
      action === "roadmap_generated" ||
      action === "node_updated";
    const iconColor = isDelete
      ? "#ef4444"
      : isSuccess
        ? "#22c55e"
        : "#3b82f6";
    const Icon =
      isDelete || isSuccess ? CheckmarkCircle02Icon : Target02Icon;

    return (
      <ToolCardShell>
        <View className="flex-row items-center gap-2">
          <AppIcon icon={Icon} size={16} color={iconColor} />
          <Text className="text-sm text-zinc-100 flex-1">{data.message}</Text>
        </View>
      </ToolCardShell>
    );
  }

  return null;
}

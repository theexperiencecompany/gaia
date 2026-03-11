import { Card } from "heroui-native";
import { View } from "react-native";
import { Text } from "@/components/ui/text";

export interface GoalNode {
  id?: string;
  data?: {
    title?: string;
    label?: string;
    isComplete?: boolean;
    type?: string;
  };
}

export interface GoalItem {
  id?: string;
  title?: string;
  description?: string;
  progress?: number;
  status?: string;
  created_at?: string;
  todo_project_id?: string;
  roadmap?: {
    nodes?: GoalNode[];
  };
}

export interface GoalStats {
  total_goals?: number;
  goals_with_roadmaps?: number;
  total_tasks?: number;
  completed_tasks?: number;
  overall_completion_rate?: number;
  active_goals_count?: number;
  active_goals?: Array<{
    id: string;
    title: string;
    progress: number;
  }>;
}

export interface GoalData {
  goals?: GoalItem[];
  stats?: GoalStats;
  action?: string;
  message?: string;
  goal_id?: string;
  deleted_goal_id?: string;
  error?: string;
}

function getProgressColor(progress: number): string {
  if (progress >= 90) return "text-green-500";
  if (progress >= 75) return "text-blue-500";
  if (progress >= 50) return "text-yellow-500";
  if (progress >= 25) return "text-orange-500";
  return "text-red-500";
}

function getProgressBgColor(progress: number): string {
  if (progress >= 90) return "bg-green-500";
  if (progress >= 75) return "bg-blue-500";
  if (progress >= 50) return "bg-yellow-500";
  if (progress >= 25) return "bg-orange-500";
  return "bg-red-500";
}

function getProgressBgFaded(progress: number): string {
  if (progress >= 90) return "bg-green-500/10";
  if (progress >= 75) return "bg-blue-500/10";
  if (progress >= 50) return "bg-yellow-500/10";
  if (progress >= 25) return "bg-orange-500/10";
  return "bg-red-500/10";
}

function formatDate(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function GoalProgressBar({ progress }: { progress: number }) {
  return (
    <View className="mt-3 mb-2">
      <View className="flex-row items-center justify-between mb-2">
        <Text className="text-sm font-medium text-muted">Progress</Text>
        <Text className={`text-sm font-semibold ${getProgressColor(progress)}`}>
          {progress}%
        </Text>
      </View>
      <View className="h-2 w-full rounded-full bg-white/10">
        <View
          className={`h-2 rounded-full ${getProgressBgColor(progress)}`}
          style={{ width: `${progress}%` }}
        />
      </View>
    </View>
  );
}

function CompactGoalCard({
  goal,
}: {
  goal: GoalItem | { id: string; title: string; progress: number };
}) {
  const progress = goal.progress || 0;
  return (
    <View className="rounded-xl bg-white/5 border border-white/8 p-3 mb-2 flex-row items-center justify-between">
      <Text className="text-sm font-medium text-foreground flex-1 mr-2">
        {goal.title}
      </Text>
      <Text className={`text-sm font-medium ${getProgressColor(progress)}`}>
        {progress}%
      </Text>
    </View>
  );
}

export function GoalCard({ data }: { data: GoalData }) {
  // Error State
  if (data.error) {
    return (
      <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
        <Card.Body className="py-3 px-4">
          <View className="flex-row items-center gap-2">
            <Text className="text-xs text-red-500">●</Text>
            <Text className="text-sm text-red-400">{data.error}</Text>
          </View>
        </Card.Body>
      </Card>
    );
  }

  // Statistics View
  if (data.action === "stats" && data.stats) {
    return (
      <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
        <Card.Body className="py-3 px-4">
          <Text className="text-sm text-foreground mb-3">
            Goal Progress Overview
          </Text>
          <View className="flex-row flex-wrap gap-2">
            <View className="rounded-xl bg-white/5 p-3 items-center flex-1 min-w-[80px]">
              <Text className="text-xl font-semibold text-foreground">
                {data.stats.total_goals}
              </Text>
              <Text className="text-xs text-muted">Total Goals</Text>
            </View>
            <View className="rounded-xl bg-white/5 p-3 items-center flex-1 min-w-[80px]">
              <Text className="text-xl font-semibold text-primary">
                {data.stats.goals_with_roadmaps}
              </Text>
              <Text className="text-xs text-muted">With Roadmaps</Text>
            </View>
            <View className="rounded-xl bg-white/5 p-3 items-center flex-1 min-w-[80px]">
              <Text className="text-xl font-semibold text-green-500">
                {data.stats.overall_completion_rate}%
              </Text>
              <Text className="text-xs text-muted">Complete</Text>
            </View>
          </View>
          <View className="flex-row flex-wrap gap-2 mt-2">
            <View className="rounded-xl bg-white/5 p-3 items-center flex-1 min-w-[80px]">
              <Text className="text-xl font-semibold text-blue-500">
                {data.stats.total_tasks}
              </Text>
              <Text className="text-xs text-muted">Total Tasks</Text>
            </View>
            <View className="rounded-xl bg-white/5 p-3 items-center flex-1 min-w-[80px]">
              <Text className="text-xl font-semibold text-green-500">
                {data.stats.completed_tasks}
              </Text>
              <Text className="text-xs text-muted">Done Tasks</Text>
            </View>
            <View className="rounded-xl bg-white/5 p-3 items-center flex-1 min-w-[80px]">
              <Text className="text-xl font-semibold text-orange-500">
                {data.stats.active_goals_count}
              </Text>
              <Text className="text-xs text-muted">Active</Text>
            </View>
          </View>

          {data.stats.active_goals && data.stats.active_goals.length > 0 && (
            <View className="mt-4">
              <Text className="text-xs font-medium text-muted mb-2">
                Top Active Goals
              </Text>
              {data.stats.active_goals.map((goal) => (
                <CompactGoalCard key={goal.id} goal={goal} />
              ))}
            </View>
          )}
        </Card.Body>
      </Card>
    );
  }

  // Progress/Loading Messages
  if (
    data.action &&
    [
      "creating",
      "fetching",
      "deleting",
      "updating_progress",
      "generating_roadmap",
    ].includes(data.action)
  ) {
    return (
      <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
        <Card.Body className="py-3 px-4">
          <View className="flex-row items-center gap-2">
            <Text className="text-xs text-blue-500">●</Text>
            <Text className="text-sm text-foreground">{data.message}</Text>
          </View>
        </Card.Body>
      </Card>
    );
  }

  // Create Goal Card
  if (data.action === "create" && data.goals && data.goals.length === 1) {
    const goal = data.goals[0];
    return (
      <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
        <Card.Body className="py-3 px-4">
          <Text className="text-sm font-medium text-foreground mb-1">
            Goal Created
          </Text>
          <Text className="text-base font-semibold text-foreground mt-2">
            {goal.title}
          </Text>
          {goal.description && (
            <Text className="text-sm text-muted mt-2 leading-relaxed">
              {goal.description}
            </Text>
          )}
        </Card.Body>
      </Card>
    );
  }

  // Goals List View
  if (data.goals && data.goals.length > 0) {
    const actionLabel =
      data.action === "search"
        ? "Search Results"
        : data.action === "roadmap_generated"
          ? "Goal with Roadmap"
          : data.action === "node_updated"
            ? "Updated Progress"
            : "Your Goals";

    return (
      <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
        <Card.Body className="py-3 px-4">
          <View className="flex-row items-center justify-between mb-3">
            <Text className="text-sm text-foreground">{actionLabel}</Text>
            <Text className="text-xs text-muted">
              {data.goals.length} {data.goals.length === 1 ? "goal" : "goals"}
            </Text>
          </View>
          {data.goals.map((goal) => {
            const roadmapTasks =
              goal.roadmap?.nodes?.filter(
                (n) => n.data?.type !== "start" && n.data?.type !== "end",
              ) || [];
            const completedTasks = roadmapTasks.filter(
              (n) => n.data?.isComplete,
            );
            const progress =
              roadmapTasks.length > 0
                ? Math.round(
                    (completedTasks.length / roadmapTasks.length) * 100,
                  )
                : goal.progress || 0;

            return (
              <View
                key={goal.id || goal.title}
                className="rounded-xl bg-white/5 border border-white/8 p-4 mb-3"
              >
                <Text className="text-base font-semibold text-foreground">
                  {goal.title}
                </Text>

                <GoalProgressBar progress={progress} />

                {/* Metadata */}
                <View className="flex-row flex-wrap items-center gap-2 mt-1">
                  {roadmapTasks.length > 0 && (
                    <View
                      className={`rounded-full px-3 py-1 ${getProgressBgFaded(progress)}`}
                    >
                      <Text
                        className={`text-xs font-medium ${getProgressColor(progress)}`}
                      >
                        {completedTasks.length}/{roadmapTasks.length} tasks
                      </Text>
                    </View>
                  )}
                  {goal.created_at && (
                    <View className="rounded-full bg-white/5 px-3 py-1">
                      <Text className="text-xs text-muted">
                        {formatDate(goal.created_at)}
                      </Text>
                    </View>
                  )}
                  {goal.todo_project_id && (
                    <View className="rounded-full bg-white/5 px-3 py-1">
                      <Text className="text-xs text-muted">
                        Linked to Todos
                      </Text>
                    </View>
                  )}
                </View>

                {/* Roadmap tasks (expanded) */}
                {roadmapTasks.length > 0 && (
                  <View className="mt-3 pt-3 border-t border-white/10">
                    <Text className="text-sm font-medium text-foreground mb-2">
                      Roadmap Tasks
                    </Text>
                    {roadmapTasks.map((node) => (
                      <View
                        key={node.id}
                        className="flex-row items-center gap-3 py-1"
                      >
                        <View
                          className={`w-4 h-4 rounded-full border-2 items-center justify-center ${
                            node.data?.isComplete
                              ? "border-green-500 bg-green-500"
                              : "border-zinc-600"
                          }`}
                        >
                          {node.data?.isComplete && (
                            <Text className="text-[8px] text-white">✓</Text>
                          )}
                        </View>
                        <Text
                          className={`text-sm ${
                            node.data?.isComplete
                              ? "text-muted line-through"
                              : "text-foreground"
                          }`}
                        >
                          {node.data?.title ||
                            node.data?.label ||
                            "Untitled Task"}
                        </Text>
                      </View>
                    ))}
                  </View>
                )}
              </View>
            );
          })}
          {data.message && (
            <Text className="text-xs text-muted mt-1">{data.message}</Text>
          )}
        </Card.Body>
      </Card>
    );
  }

  // Empty State
  if (data.action === "list" && (!data.goals || data.goals.length === 0)) {
    return (
      <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
        <Card.Body className="py-6 px-4 items-center">
          <Text className="text-sm text-foreground">No goals found</Text>
          {data.message && (
            <Text className="text-xs text-muted mt-1">{data.message}</Text>
          )}
        </Card.Body>
      </Card>
    );
  }

  // Success/Action Message
  if (data.message && !data.goals && !data.stats) {
    const isDeleteAction = data.action === "delete";
    const isSuccessAction =
      data.action &&
      ["create", "roadmap_generated", "node_updated"].includes(data.action);

    return (
      <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
        <Card.Body className="py-3 px-4">
          <View className="flex-row items-center gap-2">
            <Text
              className={`text-xs ${
                isDeleteAction
                  ? "text-red-500"
                  : isSuccessAction
                    ? "text-green-500"
                    : "text-blue-500"
              }`}
            >
              ●
            </Text>
            <Text className="text-sm text-foreground">{data.message}</Text>
          </View>
        </Card.Body>
      </Card>
    );
  }

  return null;
}

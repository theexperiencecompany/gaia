import { Button, Card, Chip } from "heroui-native";
import { View } from "react-native";
import { Text } from "@/components/ui/text";

export type GoalAction = "create" | "update" | "list" | "delete";

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

export interface GoalData {
  goals?: GoalItem[];
  action?: GoalAction;
  message?: string;
}

function getProgressBarColor(pct: number): string {
  if (pct >= 90) return "bg-emerald-500";
  if (pct >= 75) return "bg-blue-500";
  if (pct >= 50) return "bg-amber-500";
  if (pct >= 25) return "bg-orange-500";
  return "bg-red-500";
}

function getProgressChipColor(
  pct: number,
): "success" | "accent" | "warning" | "danger" {
  if (pct >= 75) return "success";
  if (pct >= 50) return "accent";
  if (pct >= 25) return "warning";
  return "danger";
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
  const progress = computeProgress(goal);
  const roadmapTasks =
    goal.roadmap?.nodes?.filter(
      (n) => n.data.type !== "start" && n.data.type !== "end",
    ) ?? [];
  const completedTasks = roadmapTasks.filter((n) => n.data.isComplete).length;
  const hasRoadmap = roadmapTasks.length > 0;

  return (
    <View className="rounded-xl bg-zinc-900 p-3 mb-2">
      <Text
        className="text-sm font-semibold text-zinc-100 mb-1"
        numberOfLines={2}
      >
        {goal.title}
      </Text>

      {goal.description && (
        <Text className="text-xs text-zinc-400 mb-2" numberOfLines={2}>
          {goal.description}
        </Text>
      )}

      {/* Progress bar with percentage chip */}
      <View className="mb-2">
        <View className="flex-row items-center justify-between mb-1">
          <Text className="text-xs text-zinc-500">Progress</Text>
          <Chip
            size="sm"
            variant="soft"
            color={getProgressChipColor(progress)}
            animation="disable-all"
          >
            <Chip.Label>{progress}%</Chip.Label>
          </Chip>
        </View>
        {/* Custom progress bar kept for precise width control */}
        <View className="h-1.5 w-full rounded-full bg-zinc-700 overflow-hidden">
          <View
            className={`h-1.5 rounded-full ${getProgressBarColor(progress)}`}
            style={{ width: `${Math.min(100, Math.max(0, progress))}%` }}
          />
        </View>
      </View>

      {/* Metadata chips */}
      <View className="flex-row flex-wrap gap-1.5">
        {hasRoadmap && (
          <Chip
            size="sm"
            variant="soft"
            color="default"
            animation="disable-all"
          >
            <Chip.Label>
              {completedTasks}/{roadmapTasks.length} tasks
            </Chip.Label>
          </Chip>
        )}

        {goal.created_at && (
          <Chip
            size="sm"
            variant="soft"
            color="default"
            animation="disable-all"
          >
            <Chip.Label>{formatDate(goal.created_at)}</Chip.Label>
          </Chip>
        )}

        {goal.todo_project_id && (
          <Chip
            size="sm"
            variant="soft"
            color="default"
            animation="disable-all"
          >
            <Chip.Label>Linked to Todos</Chip.Label>
          </Chip>
        )}
      </View>
    </View>
  );
}

function SingleGoalCreateCard({ goal }: { goal: GoalItem }) {
  const progress = computeProgress(goal);

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl overflow-hidden">
      <Card.Body className="p-0">
        {/* Header */}
        <View className="flex-row items-center gap-2 px-4 pt-4 pb-3 border-b border-zinc-800">
          <Text className="text-base" aria-label="goal">
            🎯
          </Text>
          <Text className="text-sm font-semibold text-zinc-100">
            Goal Created
          </Text>
        </View>

        {/* Content */}
        <View className="px-4 py-3">
          <Text
            className="text-base font-semibold text-zinc-100 mb-1"
            numberOfLines={2}
          >
            {goal.title}
          </Text>

          {goal.description && (
            <Text className="text-sm text-zinc-400 mb-3" numberOfLines={3}>
              {goal.description}
            </Text>
          )}

          {/* Progress bar with percentage chip */}
          <View className="mb-2">
            <View className="flex-row items-center justify-between mb-1">
              <Text className="text-xs text-zinc-500">Progress</Text>
              <Chip
                size="sm"
                variant="soft"
                color={getProgressChipColor(progress)}
                animation="disable-all"
              >
                <Chip.Label>{progress}%</Chip.Label>
              </Chip>
            </View>
            {/* Custom progress bar kept for precise width control */}
            <View className="h-1.5 w-full rounded-full bg-zinc-700 overflow-hidden">
              <View
                className={`h-1.5 rounded-full ${getProgressBarColor(progress)}`}
                style={{ width: `${Math.min(100, Math.max(0, progress))}%` }}
              />
            </View>
          </View>

          {goal.created_at && (
            <Text className="text-xs text-zinc-500 mt-1">
              Created {formatDate(goal.created_at)}
            </Text>
          )}
        </View>

        {/* View Goal action */}
        <View className="px-4 pb-4">
          <Button size="sm" className="w-full">
            View Goal
          </Button>
        </View>
      </Card.Body>
    </Card>
  );
}

export function GoalCard({ data }: { data: GoalData }) {
  const action = data.action ?? "list";

  // Single goal create — use rich card
  if (action === "create" && data.goals && data.goals.length === 1) {
    return <SingleGoalCreateCard goal={data.goals[0]} />;
  }

  // Goals list
  if (data.goals && data.goals.length > 0) {
    const headerLabel =
      action === "create"
        ? "New Goals"
        : action === "update"
          ? "Updated Goals"
          : action === "delete"
            ? "Deleted Goals"
            : "Goals";

    return (
      <Card variant="secondary" className="mx-4 my-2 rounded-xl">
        <Card.Body className="p-4">
          <View className="flex-row items-center justify-between mb-3">
            <Text className="text-xs text-muted">{headerLabel}</Text>
            <Text className="text-xs text-muted">
              {data.goals.length} {data.goals.length === 1 ? "goal" : "goals"}
            </Text>
          </View>
          {data.goals.map((goal) => (
            <GoalItemCard key={goal.id} goal={goal} />
          ))}
          {data.message && (
            <Text className="text-xs text-muted mt-1">{data.message}</Text>
          )}
        </Card.Body>
      </Card>
    );
  }

  // Action message with no goals
  if (data.message) {
    return (
      <Card variant="secondary" className="mx-4 my-2 rounded-xl">
        <Card.Body className="p-4">
          <View className="flex-row items-center gap-2">
            <Chip
              size="sm"
              variant="soft"
              color={action === "delete" ? "danger" : "success"}
              animation="disable-all"
            >
              <Chip.Label>{action === "delete" ? "✕" : "✓"}</Chip.Label>
            </Chip>
            <Text className="text-sm text-zinc-100 flex-1">{data.message}</Text>
          </View>
        </Card.Body>
      </Card>
    );
  }

  return null;
}

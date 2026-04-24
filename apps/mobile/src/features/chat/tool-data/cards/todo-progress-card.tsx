import type {
  TodoProgressData,
  TodoProgressItem,
  TodoProgressSnapshot,
} from "@gaia/shared";
import { View } from "react-native";
import {
  AppIcon,
  Cancel01Icon,
  CheckmarkCircle02Icon,
  Clock01Icon,
  Loading03Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { ToolCardShell } from "@/features/chat/tool-data/primitives";

function toTitleCase(str: string): string {
  return str
    .replace(/[-_]/g, " ")
    .replace(/\w\S*/g, (w) => w.charAt(0).toUpperCase() + w.slice(1));
}

function getProgressBarColor(pct: number): string {
  if (pct >= 100) return "#10b981"; // emerald-500
  if (pct >= 60) return "#f59e0b"; // amber-500
  if (pct > 0) return "#00bbff"; // primary
  return "#3f3f46"; // zinc-700
}

type TodoProgressStatus = TodoProgressItem["status"];

const STATUS_ICON_MAP: Record<
  TodoProgressStatus,
  typeof CheckmarkCircle02Icon
> = {
  completed: CheckmarkCircle02Icon,
  in_progress: Loading03Icon,
  pending: Clock01Icon,
  cancelled: Cancel01Icon,
};

const STATUS_COLOR: Record<TodoProgressStatus, string> = {
  completed: "#34d399", // emerald-400
  in_progress: "#00bbff", // primary
  pending: "#52525b", // zinc-600
  cancelled: "#52525b", // zinc-600
};

function TaskRow({
  todo,
  isStreaming,
}: {
  todo: TodoProgressItem;
  isStreaming?: boolean;
}) {
  const StatusIcon = STATUS_ICON_MAP[todo.status];
  const shouldSpin = todo.status === "in_progress" && isStreaming;

  return (
    <View className="flex-row items-start gap-2">
      <View className={`shrink-0 mt-0.5 ${shouldSpin ? "animate-spin" : ""}`}>
        <AppIcon
          icon={StatusIcon}
          size={16}
          color={STATUS_COLOR[todo.status]}
        />
      </View>
      <Text
        className={`text-xs flex-1 leading-relaxed ${
          todo.status === "cancelled"
            ? "text-zinc-600 line-through"
            : "text-zinc-300"
        }`}
      >
        {todo.content}
      </Text>
    </View>
  );
}

function ProgressBar({ pct }: { pct: number }) {
  const clamped = Math.min(100, Math.max(0, pct));
  return (
    <View className="h-1.5 w-full rounded-full bg-zinc-700 mb-3 overflow-hidden">
      <View
        className="h-1.5 rounded-full"
        style={{
          width: `${clamped}%`,
          backgroundColor: getProgressBarColor(pct),
        }}
      />
    </View>
  );
}

function CountChip({ completed, total }: { completed: number; total: number }) {
  return (
    <View className="px-2 py-0.5 rounded-full bg-zinc-700/60">
      <Text className="text-xs text-zinc-400">
        {completed}/{total}
      </Text>
    </View>
  );
}

function SourceSection({
  source,
  snapshot,
  isStreaming,
}: {
  source: string;
  snapshot: TodoProgressSnapshot;
  isStreaming?: boolean;
}) {
  const todos = snapshot.todos ?? [];
  const completedCount = todos.filter((t) => t.status === "completed").length;
  const pct = todos.length > 0 ? (completedCount / todos.length) * 100 : 0;

  return (
    <View>
      <View className="flex-row items-center justify-between mb-2">
        <Text className="text-xs font-medium text-zinc-400">
          {toTitleCase(source)}
        </Text>
        <CountChip completed={completedCount} total={todos.length} />
      </View>
      <ProgressBar pct={pct} />
      <View className="gap-1.5">
        {todos.map((todo) => (
          <TaskRow
            key={`${source}-${todo.id}`}
            todo={todo}
            isStreaming={isStreaming}
          />
        ))}
      </View>
    </View>
  );
}

export function TodoProgressCard({
  data,
  isStreaming,
}: {
  data: TodoProgressData;
  isStreaming?: boolean;
}) {
  const activeSources = Object.entries(data).filter(
    ([, snapshot]) => snapshot?.todos && snapshot.todos.length > 0,
  );

  if (activeSources.length === 0) return null;

  return (
    <ToolCardShell>
      <View className="gap-4">
        {activeSources.map(([source, snapshot]) => (
          <SourceSection
            key={source}
            source={source}
            snapshot={snapshot}
            isStreaming={isStreaming}
          />
        ))}
      </View>
    </ToolCardShell>
  );
}

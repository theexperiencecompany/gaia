import { Card } from "heroui-native";
import { useEffect, useRef } from "react";
import { Animated, View } from "react-native";
import { Text } from "@/components/ui/text";

export interface TodoProgressItem {
  id: string;
  content: string;
  status: "pending" | "in_progress" | "completed" | "cancelled";
}

export interface TodoProgressSnapshot {
  todos?: TodoProgressItem[];
  source?: string;
}

export type TodoProgressData = Record<string, TodoProgressSnapshot>;

function toTitleCase(str: string): string {
  return str
    .replace(/[-_]/g, " ")
    .replace(/\w\S*/g, (w) => w.charAt(0).toUpperCase() + w.slice(1));
}

function getProgressColor(pct: number): string {
  if (pct >= 100) return "#10b981";
  if (pct >= 60) return "#f59e0b";
  if (pct > 0) return "#6366f1";
  return "#3f3f46";
}

interface AnimatedProgressBarProps {
  pct: number;
  height?: number;
  color?: string;
}

function AnimatedProgressBar({
  pct,
  height = 6,
  color,
}: AnimatedProgressBarProps) {
  const animWidth = useRef(new Animated.Value(0)).current;
  const barColor = color ?? getProgressColor(pct);

  useEffect(() => {
    Animated.timing(animWidth, {
      toValue: pct,
      duration: 400,
      useNativeDriver: false,
    }).start();
  }, [pct, animWidth]);

  const widthInterp = animWidth.interpolate({
    inputRange: [0, 100],
    outputRange: ["0%", "100%"],
    extrapolate: "clamp",
  });

  return (
    <View
      style={{ height, borderRadius: height / 2 }}
      className="bg-white/10 overflow-hidden w-full"
    >
      <Animated.View
        style={{
          height,
          borderRadius: height / 2,
          width: widthInterp,
          backgroundColor: barColor,
        }}
      />
    </View>
  );
}

const STATUS_SYMBOL: Record<string, string> = {
  completed: "✓",
  in_progress: "↻",
  cancelled: "✕",
  pending: "○",
};

const STATUS_COLOR: Record<string, string> = {
  completed: "text-emerald-400",
  in_progress: "text-primary",
  cancelled: "text-zinc-500",
  pending: "text-zinc-500",
};

function SpinningIcon({ spin }: { spin: boolean }) {
  const rotation = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (!spin) return;
    const anim = Animated.loop(
      Animated.timing(rotation, {
        toValue: 1,
        duration: 1200,
        useNativeDriver: true,
      }),
    );
    anim.start();
    return () => anim.stop();
  }, [spin, rotation]);

  const rotate = rotation.interpolate({
    inputRange: [0, 1],
    outputRange: ["0deg", "360deg"],
  });

  return (
    <Animated.Text
      style={{ transform: spin ? [{ rotate }] : [] }}
      className="text-xs text-primary w-4 text-center"
    >
      {STATUS_SYMBOL.in_progress}
    </Animated.Text>
  );
}

function TaskRow({ todo }: { todo: TodoProgressItem }) {
  const isInProgress = todo.status === "in_progress";
  const isCancelled = todo.status === "cancelled";
  const colorClass = STATUS_COLOR[todo.status] ?? "text-zinc-400";

  return (
    <View className="flex-row items-start gap-2 mb-1.5">
      {isInProgress ? (
        <SpinningIcon spin />
      ) : (
        <Text className={`text-xs w-4 text-center ${colorClass}`}>
          {STATUS_SYMBOL[todo.status] ?? "○"}
        </Text>
      )}
      <Text
        className={`text-xs flex-1 leading-relaxed ${colorClass} ${
          isCancelled ? "line-through" : ""
        }`}
      >
        {todo.content}
      </Text>
    </View>
  );
}

function SourceBlock({
  source,
  todos,
}: {
  source: string;
  todos: TodoProgressItem[];
}) {
  const completedCount = todos.filter((t) => t.status === "completed").length;
  const pct = todos.length > 0 ? (completedCount / todos.length) * 100 : 0;

  return (
    <View className="rounded-xl bg-white/5 border border-white/[0.08] px-3 py-2.5 mb-2">
      <View className="flex-row items-center justify-between mb-1.5">
        <Text className="text-xs text-foreground font-medium">
          {toTitleCase(source)}
        </Text>
        <Text className="text-[10px] text-zinc-500">
          {completedCount}/{todos.length}
        </Text>
      </View>
      <View className="mb-2">
        <AnimatedProgressBar pct={pct} height={4} />
      </View>
      {todos.map((todo) => (
        <TaskRow key={`${source}-${todo.id}`} todo={todo} />
      ))}
    </View>
  );
}

export function TodoProgressCard({ data }: { data: TodoProgressData }) {
  const activeSources = Object.entries(data).filter(
    ([, snapshot]) => snapshot?.todos && snapshot.todos.length > 0,
  );

  if (activeSources.length === 0) return null;

  const allTodos = activeSources.flatMap(([, s]) => s.todos ?? []);
  const completedCount = allTodos.filter(
    (t) => t.status === "completed",
  ).length;
  const totalCount = allTodos.length;
  const overallPct =
    totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0;

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        <View className="flex-row items-center justify-between mb-1.5">
          <Text className="text-xs text-zinc-400">Task Progress</Text>
          <Text className="text-xs text-zinc-500">
            {completedCount}/{totalCount}
          </Text>
        </View>
        <View className="mb-1.5">
          <AnimatedProgressBar pct={overallPct} height={6} />
        </View>
        <Text className="text-[10px] text-zinc-500 mb-2.5">
          {overallPct}% complete
          {activeSources.length > 1 ? ` • ${activeSources.length} sources` : ""}
        </Text>
        {activeSources.map(([source, snapshot]) => (
          <SourceBlock
            key={source}
            source={source}
            todos={snapshot.todos ?? []}
          />
        ))}
      </Card.Body>
    </Card>
  );
}

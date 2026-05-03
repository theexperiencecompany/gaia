import type {
  TodoProgressData,
  TodoProgressItem,
  TodoProgressSnapshot,
} from "@gaia/shared";
import { useEffect, useMemo, useRef, useState } from "react";
import { Pressable, View } from "react-native";
import Animated, {
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withTiming,
} from "react-native-reanimated";
import {
  AppIcon,
  ArrowDown02Icon,
  Cancel01Icon,
  CheckmarkCircle02Icon,
  DashedLineCircleIcon,
  Loading03Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { ToolCardShell } from "@/features/chat/tool-data/primitives";

// -- Status meta -------------------------------------------------------------

type TodoProgressStatus = TodoProgressItem["status"];

const STATUS_ICON_MAP: Record<
  TodoProgressStatus,
  typeof CheckmarkCircle02Icon
> = {
  completed: CheckmarkCircle02Icon,
  in_progress: Loading03Icon,
  pending: DashedLineCircleIcon,
  cancelled: Cancel01Icon,
};

const STATUS_COLOR: Record<TodoProgressStatus, string> = {
  completed: "#34d399", // emerald-400
  in_progress: "#00bbff", // primary
  pending: "#52525b", // zinc-600
  cancelled: "#52525b", // zinc-600
};

// -- Helpers -----------------------------------------------------------------

function toTitleCase(str: string): string {
  return str
    .replace(/[-_]/g, " ")
    .replace(/\w\S*/g, (w) => w.charAt(0).toUpperCase() + w.slice(1));
}

function getProgressBarColor(pct: number): string {
  if (pct >= 100) return "#10b981"; // emerald-500 (success)
  if (pct >= 60) return "#f59e0b"; // amber-500 (warning)
  if (pct > 0) return "#00bbff"; // primary
  return "#3f3f46"; // zinc-700 (default)
}

function computeSourceProgress(snapshot: TodoProgressSnapshot): {
  todos: TodoProgressItem[];
  completed: number;
  total: number;
  pct: number;
} {
  const todos = snapshot.todos ?? [];
  const completed = todos.filter((t) => t.status === "completed").length;
  const total = todos.length;
  const pct = total > 0 ? (completed / total) * 100 : 0;
  return { todos, completed, total, pct };
}

// -- Animated spinner --------------------------------------------------------

function AnimatedSpinner({ color }: { color: string }) {
  const rotation = useSharedValue(0);

  useEffect(() => {
    rotation.value = withRepeat(
      withTiming(360, { duration: 1000, easing: Easing.linear }),
      -1,
      false,
    );
  }, [rotation]);

  const animatedStyle = useAnimatedStyle(() => ({
    transform: [{ rotate: `${rotation.value}deg` }],
  }));

  return (
    <Animated.View style={[{ width: 16, height: 16 }, animatedStyle]}>
      <AppIcon icon={Loading03Icon} size={16} color={color} />
    </Animated.View>
  );
}

// -- Task row ----------------------------------------------------------------

function TaskRow({
  todo,
  isStreaming,
}: {
  todo: TodoProgressItem;
  isStreaming?: boolean;
}) {
  const StatusIcon = STATUS_ICON_MAP[todo.status];
  const color = STATUS_COLOR[todo.status];
  const shouldSpin = todo.status === "in_progress" && isStreaming;

  return (
    <View className="flex-row items-start gap-2">
      <View className="shrink-0 mt-0.5">
        {shouldSpin ? (
          <AnimatedSpinner color={color} />
        ) : (
          <AppIcon icon={StatusIcon} size={16} color={color} />
        )}
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

function TaskList({
  todos,
  isStreaming,
}: {
  todos: TodoProgressItem[];
  isStreaming?: boolean;
}) {
  return (
    <View className="gap-1.5">
      {todos.map((todo) => (
        <TaskRow key={todo.id} todo={todo} isStreaming={isStreaming} />
      ))}
    </View>
  );
}

// -- Count chip --------------------------------------------------------------

function CountChip({
  completed,
  total,
  textTone = "muted",
}: {
  completed: number;
  total: number;
  textTone?: "muted" | "dim";
}) {
  const textClass = textTone === "dim" ? "text-zinc-500" : "text-zinc-400";
  return (
    <View className="px-2 py-0.5 rounded-full bg-zinc-700/60">
      <Text className={`text-xs ${textClass}`}>
        {completed}/{total}
      </Text>
    </View>
  );
}

// -- Animated progress bar ---------------------------------------------------

function ProgressBar({ pct, height = 6 }: { pct: number; height?: number }) {
  const clamped = Math.min(100, Math.max(0, pct));
  const width = useSharedValue(0);
  const color = getProgressBarColor(clamped);

  useEffect(() => {
    width.value = withTiming(clamped, { duration: 400 });
  }, [clamped, width]);

  const barStyle = useAnimatedStyle(() => ({
    width: `${width.value}%` as `${number}%`,
  }));

  return (
    <View
      style={{
        height,
        backgroundColor: "#3f3f46", // zinc-700
        borderRadius: height / 2,
        overflow: "hidden",
        width: "100%",
      }}
    >
      <Animated.View
        style={[
          barStyle,
          {
            height: "100%",
            backgroundColor: color,
            borderRadius: height / 2,
          },
        ]}
      />
    </View>
  );
}

// -- Single-source card ------------------------------------------------------

function SingleSourceCard({
  source,
  snapshot,
  isStreaming,
}: {
  source: string;
  snapshot: TodoProgressSnapshot;
  isStreaming?: boolean;
}) {
  const { todos, completed, total, pct } = computeSourceProgress(snapshot);

  return (
    <ToolCardShell>
      <View className="flex-row items-center justify-between mb-2">
        <Text
          className="text-xs font-medium text-zinc-400 flex-1"
          numberOfLines={1}
        >
          {toTitleCase(source)}
        </Text>
        <CountChip completed={completed} total={total} />
      </View>
      <View className="mb-3">
        <ProgressBar pct={pct} />
      </View>
      <TaskList todos={todos} isStreaming={isStreaming} />
    </ToolCardShell>
  );
}

// -- Multi-source accordion --------------------------------------------------

function MultiSourceAccordion({
  activeSources,
  data,
  isStreaming,
}: {
  activeSources: string[];
  data: TodoProgressData;
  isStreaming?: boolean;
}) {
  const prevDataRef = useRef<TodoProgressData>({});

  // Mirror web: default-expand the source whose snapshot most recently changed.
  const defaultExpandedKey = useMemo(() => {
    let latest: string | null = null;
    for (const key of activeSources) {
      if (data[key] !== prevDataRef.current[key]) {
        latest = key;
      }
    }
    prevDataRef.current = data;
    return latest ?? activeSources[activeSources.length - 1];
  }, [activeSources, data]);

  const [expandedKey, setExpandedKey] = useState<string | null>(
    defaultExpandedKey,
  );

  // When defaultExpandedKey changes (a new snapshot arrives), follow it.
  useEffect(() => {
    setExpandedKey(defaultExpandedKey);
  }, [defaultExpandedKey]);

  return (
    <ToolCardShell className="p-1">
      {activeSources.map((source) => {
        const snapshot = data[source];
        const { todos, completed, total, pct } =
          computeSourceProgress(snapshot);
        const isOpen = expandedKey === source;

        return (
          <View key={source} className="px-2">
            <Pressable
              onPress={() => setExpandedKey(isOpen ? null : source)}
              className="flex-row items-center gap-2 py-2"
              hitSlop={4}
            >
              <Text
                className="text-xs font-medium text-zinc-400 flex-1 min-w-0"
                numberOfLines={1}
              >
                {toTitleCase(source)}
              </Text>
              <View style={{ width: 64 }}>
                <ProgressBar pct={pct} height={6} />
              </View>
              <CountChip completed={completed} total={total} textTone="dim" />
              <View
                style={{
                  transform: [{ rotate: isOpen ? "0deg" : "-90deg" }],
                }}
              >
                <AppIcon icon={ArrowDown02Icon} size={12} color="#71717a" />
              </View>
            </Pressable>
            {isOpen && (
              <View className="pb-2 pt-0">
                <TaskList todos={todos} isStreaming={isStreaming} />
              </View>
            )}
          </View>
        );
      })}
    </ToolCardShell>
  );
}

// -- Main entry --------------------------------------------------------------

export function TodoProgressCard({
  data,
  isStreaming,
}: {
  data: TodoProgressData;
  isStreaming?: boolean;
}) {
  const activeSources = Object.keys(data).filter(
    (s) => data[s]?.todos && (data[s].todos?.length ?? 0) > 0,
  );

  if (activeSources.length === 0) return null;

  if (activeSources.length === 1) {
    return (
      <SingleSourceCard
        source={activeSources[0]}
        snapshot={data[activeSources[0]]}
        isStreaming={isStreaming}
      />
    );
  }

  return (
    <MultiSourceAccordion
      activeSources={activeSources}
      data={data}
      isStreaming={isStreaming}
    />
  );
}

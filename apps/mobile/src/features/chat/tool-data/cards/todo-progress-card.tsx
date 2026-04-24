import { useMemo, useRef, useState } from "react";
import { Pressable, View } from "react-native";
import {
  AppIcon,
  ArrowRight01Icon,
  Cancel01Icon,
  CheckmarkCircle02Icon,
  Loading03Icon,
} from "@/components/icons";
import type { AnyIcon } from "@/components/icons/app-icon";
import { Text } from "@/components/ui/text";
import {
  ToolCardInner,
  ToolCardShell,
} from "@/features/chat/tool-data/primitives";

export type TodoProgressStatus =
  | "pending"
  | "in_progress"
  | "completed"
  | "cancelled";

export interface TodoProgressItem {
  id: string;
  content: string;
  status: TodoProgressStatus;
}

export interface TodoProgressSnapshot {
  todos: TodoProgressItem[];
  source?: string;
}

export type TodoProgressData = Record<string, TodoProgressSnapshot>;

const STATUS_ICON: Record<TodoProgressStatus, AnyIcon | null> = {
  completed: CheckmarkCircle02Icon,
  in_progress: Loading03Icon,
  pending: null, // rendered as a dashed circle via View
  cancelled: Cancel01Icon,
};

const STATUS_COLOR: Record<TodoProgressStatus, string> = {
  completed: "#34d399", // emerald-400
  in_progress: "#00bbff",
  pending: "#52525b", // zinc-600
  cancelled: "#52525b",
};

function toTitleCase(str: string): string {
  return str
    .replace(/[-_]/g, " ")
    .replace(/\w\S*/g, (w) => w.charAt(0).toUpperCase() + w.slice(1));
}

function getProgressBarColor(pct: number): string {
  if (pct >= 100) return "bg-green-500";
  if (pct >= 60) return "bg-yellow-500";
  if (pct > 0) return "bg-primary";
  return "bg-zinc-700";
}

function StatusIconView({ status }: { status: TodoProgressStatus }) {
  const color = STATUS_COLOR[status];
  const Icon = STATUS_ICON[status];

  if (status === "pending") {
    // Dashed-line circle via bordered View (no DashedLineCircleIcon on mobile)
    return (
      <View
        className="h-4 w-4 rounded-full"
        style={{
          borderWidth: 1.5,
          borderColor: color,
          borderStyle: "dashed",
        }}
      />
    );
  }

  if (!Icon) return null;

  return <AppIcon icon={Icon} size={16} color={color} />;
}

function TaskRow({
  todo,
  isStreaming,
}: {
  todo: TodoProgressItem;
  isStreaming?: boolean;
}) {
  return (
    <View className="flex-row items-start gap-2">
      <View className="shrink-0 mt-0.5">
        <StatusIconView status={todo.status} isStreaming={isStreaming} />
      </View>
      <Text
        className={`flex-1 text-xs leading-5 ${
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

function SourceTaskList({
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

function CountPill({
  completed,
  total,
}: {
  completed: number;
  total: number;
}) {
  return (
    <View className="rounded-full bg-zinc-700 px-2 py-0.5">
      <Text className="text-[11px] text-zinc-400">
        {completed}/{total}
      </Text>
    </View>
  );
}

function ProgressBar({ pct, className }: { pct: number; className?: string }) {
  const clamped = Math.min(100, Math.max(0, pct));
  return (
    <View
      className={`h-1.5 rounded-full bg-zinc-700 overflow-hidden ${className ?? ""}`}
    >
      <View
        className={`h-1.5 rounded-full ${getProgressBarColor(clamped)}`}
        style={{ width: `${clamped}%` }}
      />
    </View>
  );
}

function SingleSourceCard({
  source,
  todos,
  isStreaming,
}: {
  source: string;
  todos: TodoProgressItem[];
  isStreaming?: boolean;
}) {
  const completedCount = todos.filter((t) => t.status === "completed").length;
  const pct = todos.length > 0 ? (completedCount / todos.length) * 100 : 0;

  return (
    <ToolCardShell>
      <View className="flex-row items-center justify-between mb-2">
        <Text className="text-xs font-medium text-zinc-400">
          {toTitleCase(source)}
        </Text>
        <CountPill completed={completedCount} total={todos.length} />
      </View>
      <ProgressBar pct={pct} className="mb-3" />
      <SourceTaskList todos={todos} isStreaming={isStreaming} />
    </ToolCardShell>
  );
}

function MultiSourceAccordionItem({
  source,
  snapshot,
  isOpen,
  onToggle,
  isStreaming,
}: {
  source: string;
  snapshot: TodoProgressSnapshot;
  isOpen: boolean;
  onToggle: () => void;
  isStreaming?: boolean;
}) {
  const todos = snapshot.todos;
  const completedCount = todos.filter((t) => t.status === "completed").length;
  const pct = todos.length > 0 ? (completedCount / todos.length) * 100 : 0;

  return (
    <View>
      <Pressable
        onPress={onToggle}
        className="flex-row items-center gap-2 py-2 px-2"
      >
        <View
          style={{ transform: [{ rotate: isOpen ? "90deg" : "0deg" }] }}
        >
          <AppIcon icon={ArrowRight01Icon} size={12} color="#71717a" />
        </View>
        <Text
          className="text-xs font-medium text-zinc-400 flex-1"
          numberOfLines={1}
        >
          {toTitleCase(source)}
        </Text>
        <ProgressBar pct={pct} className="w-16" />
        <CountPill completed={completedCount} total={todos.length} />
      </Pressable>
      {isOpen ? (
        <View className="pb-2 px-2">
          <SourceTaskList todos={todos} isStreaming={isStreaming} />
        </View>
      ) : null}
    </View>
  );
}

function MultiSourceAccordion({
  activeSources,
  todo_progress,
  isStreaming,
}: {
  activeSources: string[];
  todo_progress: TodoProgressData;
  isStreaming?: boolean;
}) {
  const prevDataRef = useRef<TodoProgressData>({});

  const defaultOpenKey = useMemo(() => {
    let latest: string | null = null;
    for (const key of activeSources) {
      if (todo_progress[key] !== prevDataRef.current[key]) {
        latest = key;
      }
    }
    prevDataRef.current = todo_progress;
    return latest ?? activeSources[activeSources.length - 1];
  }, [activeSources, todo_progress]);

  const [openKey, setOpenKey] = useState<string | null>(defaultOpenKey);

  return (
    <ToolCardShell className="p-1">
      {activeSources.map((source) => (
        <MultiSourceAccordionItem
          key={source}
          source={source}
          snapshot={todo_progress[source]}
          isOpen={openKey === source}
          onToggle={() =>
            setOpenKey((prev) => (prev === source ? null : source))
          }
          isStreaming={isStreaming}
        />
      ))}
    </ToolCardShell>
  );
}

export function TodoProgressCard({
  data,
  isStreaming,
}: {
  data: TodoProgressData;
  isStreaming?: boolean;
}) {
  const sources = Object.keys(data);
  if (sources.length === 0) return null;

  const activeSources = sources.filter(
    (s) => data[s]?.todos && data[s].todos.length > 0,
  );
  if (activeSources.length === 0) return null;

  if (activeSources.length === 1) {
    const source = activeSources[0];
    return (
      <SingleSourceCard
        source={source}
        todos={data[source].todos}
        isStreaming={isStreaming}
      />
    );
  }

  return (
    <MultiSourceAccordion
      activeSources={activeSources}
      todo_progress={data}
      isStreaming={isStreaming}
    />
  );
}


import { Card, Checkbox, Chip } from "heroui-native";
import { View } from "react-native";
import { Text } from "@/components/ui/text";

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

function toTitleCase(str: string): string {
  return str
    .replace(/[-_]/g, " ")
    .replace(/\w\S*/g, (w) => w.charAt(0).toUpperCase() + w.slice(1));
}

function getProgressBarWidth(pct: number): `${number}%` {
  const clamped = Math.min(100, Math.max(0, pct));
  return `${clamped}%`;
}

function getProgressBarColor(pct: number): string {
  if (pct >= 100) return "bg-emerald-500";
  if (pct >= 60) return "bg-amber-500";
  if (pct > 0) return "bg-primary";
  return "bg-zinc-700";
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
  const todos = snapshot.todos;
  const completedCount = todos.filter((t) => t.status === "completed").length;
  const pct = todos.length > 0 ? (completedCount / todos.length) * 100 : 0;

  return (
    <View className="mb-3 last:mb-0">
      <View className="flex-row items-center justify-between mb-1.5">
        <Text className="text-xs font-medium text-zinc-400">
          {toTitleCase(source)}
        </Text>
        <Chip size="sm" variant="soft" color="default" animation="disable-all">
          <Chip.Label>
            {completedCount}/{todos.length}
          </Chip.Label>
        </Chip>
      </View>

      {/* Progress bar — kept as custom View for precise control */}
      <View className="h-1.5 w-full rounded-full bg-zinc-700 mb-2 overflow-hidden">
        <View
          className={`h-1.5 rounded-full ${getProgressBarColor(pct)}`}
          style={{ width: getProgressBarWidth(pct) }}
        />
      </View>

      {/* Task list */}
      <View className="gap-1.5">
        {todos.map((todo) => (
          <View
            key={`${source}-${todo.id}`}
            className="flex-row items-center gap-2"
          >
            <Checkbox
              isSelected={todo.status === "completed"}
              isDisabled
              animation="disable-all"
              className={
                todo.status === "in_progress" && isStreaming
                  ? "opacity-70"
                  : undefined
              }
            />
            <Text
              className={`text-xs flex-1 leading-relaxed ${todo.status === "cancelled" ? "text-zinc-600 line-through" : todo.status === "completed" ? "text-zinc-400" : "text-zinc-300"}`}
            >
              {todo.content}
            </Text>
          </View>
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

  const allTodos = activeSources.flatMap(([, snapshot]) => snapshot.todos);
  const totalCompleted = allTodos.filter(
    (t) => t.status === "completed",
  ).length;

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="p-4">
        <View className="flex-row items-center justify-between mb-3">
          <Text className="text-xs text-muted">
            {isStreaming ? "Processing tasks..." : "Task Progress"}
          </Text>
          <Chip
            size="sm"
            variant="soft"
            color="default"
            animation="disable-all"
          >
            <Chip.Label>
              {totalCompleted}/{allTodos.length} complete
            </Chip.Label>
          </Chip>
        </View>

        {activeSources.map(([source, snapshot]) => (
          <SourceSection
            key={source}
            source={source}
            snapshot={snapshot}
            isStreaming={isStreaming}
          />
        ))}
      </Card.Body>
    </Card>
  );
}

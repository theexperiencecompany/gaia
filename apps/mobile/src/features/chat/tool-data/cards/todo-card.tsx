import { Card, Checkbox, Chip, PressableFeedback } from "heroui-native";
import { View } from "react-native";
import { Text } from "@/components/ui/text";

export type TodoPriority = "high" | "medium" | "low" | "none";
export type TodoAction =
  | "list"
  | "create"
  | "update"
  | "delete"
  | "search"
  | "stats";

export interface TodoSubtask {
  id: string;
  title: string;
  completed: boolean;
}

export interface TodoProject {
  id: string;
  name: string;
  color?: string;
}

export interface TodoItem {
  id: string;
  title: string;
  completed: boolean;
  priority: TodoPriority;
  labels: string[];
  due_date?: string;
  project?: TodoProject;
  subtasks: TodoSubtask[];
  description?: string;
}

export interface TodoStats {
  total: number;
  completed: number;
  pending: number;
  overdue: number;
  today: number;
  upcoming: number;
}

export interface TodoData {
  todos?: TodoItem[];
  projects?: Array<{
    id: string;
    name: string;
    color?: string;
    todo_count?: number;
    completion_percentage?: number;
  }>;
  stats?: TodoStats;
  action?: TodoAction;
  message?: string;
}

const PRIORITY_CHIP_COLOR: Record<
  Exclude<TodoPriority, "none">,
  "danger" | "warning" | "accent"
> = {
  high: "danger",
  medium: "warning",
  low: "accent",
};

function formatDueDate(dateStr: string): {
  label: string;
  isOverdue: boolean;
  isToday: boolean;
} {
  const due = new Date(dateStr);
  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const dueStart = new Date(due.getFullYear(), due.getMonth(), due.getDate());
  const diffDays = Math.round(
    (dueStart.getTime() - todayStart.getTime()) / (1000 * 60 * 60 * 24),
  );

  const isOverdue = diffDays < 0;
  const isToday = diffDays === 0;

  let label: string;
  if (diffDays === 0) label = "Today";
  else if (diffDays === 1) label = "Tomorrow";
  else if (diffDays === -1) label = "Yesterday";
  else if (diffDays > 1 && diffDays < 7)
    label = due.toLocaleDateString("en-US", { weekday: "short" });
  else
    label = due.toLocaleDateString("en-US", { month: "short", day: "numeric" });

  return { label, isOverdue, isToday };
}

function TodoItemRow({
  todo,
  onPress,
}: {
  todo: TodoItem;
  onPress?: () => void;
}) {
  const completedSubtasks = todo.subtasks.filter((s) => s.completed).length;
  const totalSubtasks = todo.subtasks.length;
  const dueInfo = todo.due_date ? formatDueDate(todo.due_date) : null;

  return (
    <PressableFeedback
      onPress={onPress}
      isDisabled={!onPress}
      className="rounded-xl bg-zinc-900 p-3 mb-2"
    >
      <View className="flex-row items-start gap-2">
        <Checkbox
          isSelected={todo.completed}
          isDisabled
          className="mt-0.5 shrink-0"
          animation="disable-all"
        />
        <View className="flex-1">
          <Text
            className={`text-sm font-medium ${todo.completed ? "text-zinc-500 line-through" : "text-zinc-100"}`}
            numberOfLines={2}
          >
            {todo.title}
          </Text>

          <View className="flex-row flex-wrap items-center gap-1.5 mt-1.5">
            {todo.priority !== "none" && (
              <Chip
                size="sm"
                variant="soft"
                color={PRIORITY_CHIP_COLOR[todo.priority]}
                animation="disable-all"
              >
                <Chip.Label className="capitalize">{todo.priority}</Chip.Label>
              </Chip>
            )}

            {dueInfo && (
              <Chip
                size="sm"
                variant="soft"
                color={
                  dueInfo.isOverdue
                    ? "danger"
                    : dueInfo.isToday
                      ? "warning"
                      : "default"
                }
                animation="disable-all"
              >
                <Chip.Label>{dueInfo.label}</Chip.Label>
              </Chip>
            )}

            {todo.project && (
              <Chip
                size="sm"
                variant="soft"
                color="default"
                animation="disable-all"
              >
                {todo.project.color ? (
                  <View
                    className="h-2 w-2 rounded-full"
                    style={{ backgroundColor: todo.project.color }}
                  />
                ) : null}
                <Chip.Label numberOfLines={1}>{todo.project.name}</Chip.Label>
              </Chip>
            )}

            {totalSubtasks > 0 && (
              <Chip
                size="sm"
                variant="soft"
                color="default"
                animation="disable-all"
              >
                <Chip.Label>
                  {completedSubtasks}/{totalSubtasks} subtasks
                </Chip.Label>
              </Chip>
            )}
          </View>
        </View>
      </View>
    </PressableFeedback>
  );
}

function StatBox({
  value,
  label,
  color,
}: {
  value: number;
  label: string;
  color: string;
}) {
  return (
    <View className="flex-1 rounded-xl bg-zinc-900 p-3 items-center">
      <Text className={`text-xl font-semibold ${color}`}>{value}</Text>
      <Text className="text-xs text-zinc-500 mt-0.5">{label}</Text>
    </View>
  );
}

export function TodoCard({ data }: { data: TodoData }) {
  const action = data.action ?? "list";

  // Stats view
  if (action === "stats" && data.stats) {
    const s = data.stats;
    return (
      <Card variant="secondary" className="mx-4 my-2 rounded-xl">
        <Card.Body className="p-4">
          <Text className="text-xs text-muted mb-3">Task Overview</Text>
          <View className="flex-row gap-2 mb-2">
            <StatBox value={s.total} label="Total" color="text-zinc-100" />
            <StatBox
              value={s.completed}
              label="Done"
              color="text-emerald-500"
            />
            <StatBox value={s.pending} label="Pending" color="text-amber-500" />
          </View>
          {(s.overdue > 0 || s.today > 0 || s.upcoming > 0) && (
            <View className="flex-row gap-2">
              {s.overdue > 0 && (
                <StatBox
                  value={s.overdue}
                  label="Overdue"
                  color="text-red-500"
                />
              )}
              {s.today > 0 && (
                <StatBox value={s.today} label="Today" color="text-blue-500" />
              )}
              {s.upcoming > 0 && (
                <StatBox
                  value={s.upcoming}
                  label="Soon"
                  color="text-purple-500"
                />
              )}
            </View>
          )}
        </Card.Body>
      </Card>
    );
  }

  // Projects view
  if (data.projects && data.projects.length > 0 && !data.todos) {
    return (
      <Card variant="secondary" className="mx-4 my-2 rounded-xl">
        <Card.Body className="p-4">
          <Text className="text-xs text-muted mb-3">Your Projects</Text>
          {data.projects.map((project) => (
            <View
              key={project.id}
              className="flex-row items-center justify-between rounded-xl bg-zinc-900 p-3 mb-2"
            >
              <View className="flex-row items-center gap-2 flex-1">
                {project.color ? (
                  <View
                    className="h-3 w-3 rounded-full"
                    style={{ backgroundColor: project.color }}
                  />
                ) : null}
                <Text
                  className="text-sm font-medium text-zinc-100"
                  numberOfLines={1}
                >
                  {project.name}
                </Text>
              </View>
              <View className="flex-row items-center gap-1">
                {project.todo_count !== undefined && (
                  <Text className="text-xs text-zinc-500">
                    {project.todo_count} tasks
                  </Text>
                )}
                {project.completion_percentage !== undefined && (
                  <Text className="text-xs text-zinc-500">
                    {" · "}
                    {Math.round(project.completion_percentage)}%
                  </Text>
                )}
              </View>
            </View>
          ))}
        </Card.Body>
      </Card>
    );
  }

  // Todos list view
  if (data.todos && data.todos.length > 0) {
    const headerLabel =
      action === "search"
        ? "Search Results"
        : action === "create"
          ? "New Task"
          : action === "update"
            ? "Updated Tasks"
            : action === "delete"
              ? "Deleted Tasks"
              : "Tasks";

    return (
      <Card variant="secondary" className="mx-4 my-2 rounded-xl">
        <Card.Body className="p-4">
          <View className="flex-row items-center justify-between mb-3">
            <Text className="text-xs text-muted">{headerLabel}</Text>
            <Text className="text-xs text-muted">
              {data.todos.length} {data.todos.length === 1 ? "task" : "tasks"}
            </Text>
          </View>
          {data.todos.map((todo) => (
            <TodoItemRow key={todo.id} todo={todo} />
          ))}
          {data.message && (
            <Text className="text-xs text-muted mt-1">{data.message}</Text>
          )}
        </Card.Body>
      </Card>
    );
  }

  // Empty state for list action
  if (action === "list" && (!data.todos || data.todos.length === 0)) {
    return (
      <Card variant="secondary" className="mx-4 my-2 rounded-xl">
        <Card.Body className="p-4 items-center">
          <Text className="text-zinc-300 text-sm">No tasks found</Text>
          {data.message && (
            <Text className="text-xs text-muted mt-1">{data.message}</Text>
          )}
        </Card.Body>
      </Card>
    );
  }

  // Action message (delete/success with no todos)
  if (data.message && !data.todos && !data.stats && !data.projects) {
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

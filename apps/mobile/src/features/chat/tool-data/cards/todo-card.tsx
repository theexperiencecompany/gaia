import { Card } from "heroui-native";
import { View } from "react-native";
import {
  AppIcon,
  Calendar03Icon,
  CheckmarkCircle02Icon,
  Flag02Icon,
  FolderIcon,
  LayoutGridIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { formatDueDate } from "@gaia/shared/tool-utils";

export type TodoStatus = "pending" | "in_progress" | "completed" | "cancelled";

export interface TodoItem {
  id?: string;
  title?: string;
  description?: string;
  completed?: boolean;
  status?: TodoStatus;
  priority?: "high" | "medium" | "low" | "none";
  due_date?: string;
  labels?: string[];
  project?: { name?: string; color?: string };
  subtasks?: Array<{ id?: string; title?: string; completed?: boolean }>;
}

export interface TodoProject {
  id?: string;
  name?: string;
  color?: string;
  todo_count?: number;
  completion_percentage?: number;
}

export interface TodoStats {
  total?: number;
  completed?: number;
  pending?: number;
  overdue?: number;
  today?: number;
  upcoming?: number;
}

export interface TodoData {
  todos?: TodoItem[];
  projects?: TodoProject[];
  stats?: TodoStats;
  action?: string;
  message?: string;
}

const priorityConfig: Record<
  string,
  { bgColor: string; textColor: string; label: string; iconColor: string }
> = {
  high: {
    bgColor: "bg-red-500/10",
    textColor: "text-red-500",
    label: "High",
    iconColor: "#ef4444",
  },
  medium: {
    bgColor: "bg-yellow-500/10",
    textColor: "text-yellow-500",
    label: "Medium",
    iconColor: "#eab308",
  },
  low: {
    bgColor: "bg-blue-500/10",
    textColor: "text-blue-500",
    label: "Low",
    iconColor: "#3b82f6",
  },
  none: {
    bgColor: "",
    textColor: "text-muted",
    label: "",
    iconColor: "#71717a",
  },
};

const statusConfig: Record<
  string,
  {
    bgColor: string;
    textColor: string;
    checkColor: string;
    borderColor: string;
    label: string;
  }
> = {
  pending: {
    bgColor: "",
    textColor: "text-muted",
    checkColor: "#71717a",
    borderColor: "border-zinc-600",
    label: "Pending",
  },
  in_progress: {
    bgColor: "bg-primary/10",
    textColor: "text-primary",
    checkColor: "#6366f1",
    borderColor: "border-primary",
    label: "In Progress",
  },
  completed: {
    bgColor: "bg-green-500/10",
    textColor: "text-green-500",
    checkColor: "#22c55e",
    borderColor: "border-green-500",
    label: "Completed",
  },
  cancelled: {
    bgColor: "bg-red-500/10",
    textColor: "text-red-500",
    checkColor: "#ef4444",
    borderColor: "border-red-500",
    label: "Cancelled",
  },
};

function getTodoStatus(todo: TodoItem): TodoStatus {
  if (todo.status) return todo.status;
  if (todo.completed) return "completed";
  return "pending";
}

function isTodoDone(todo: TodoItem): boolean {
  const s = getTodoStatus(todo);
  return s === "completed" || s === "cancelled";
}

function isOverdue(date: string): boolean {
  return new Date(date) < new Date();
}

function TodoCheckbox({ todo }: { todo: TodoItem }) {
  const status = getTodoStatus(todo);
  const cfg = statusConfig[status] ?? statusConfig.pending;
  const done = isTodoDone(todo);

  return (
    <View
      className={`mt-0.5 w-4 h-4 rounded-full border-2 items-center justify-center ${cfg.borderColor}`}
      style={
        done
          ? {
              backgroundColor:
                status === "completed"
                  ? "rgba(34,197,94,0.9)"
                  : "rgba(239,68,68,0.85)",
            }
          : undefined
      }
    >
      {done && (
        <AppIcon
          icon={CheckmarkCircle02Icon}
          size={10}
          color="#ffffff"
          strokeWidth={2.5}
        />
      )}
    </View>
  );
}

function StatusBadge({ status }: { status: TodoStatus }) {
  const cfg = statusConfig[status] ?? statusConfig.pending;
  if (status === "pending") return null;
  return (
    <View className={`rounded-full px-2 py-0.5 ${cfg.bgColor}`}>
      <Text className={`text-xs ${cfg.textColor}`}>{cfg.label}</Text>
    </View>
  );
}

export function TodoCard({ data }: { data: TodoData }) {
  // Statistics View
  if (data.action === "stats" && data.stats) {
    return (
      <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
        <Card.Body className="py-3 px-4">
          <Text className="text-sm text-foreground mb-3">Task Overview</Text>
          <View className="flex-row flex-wrap gap-2">
            <View className="rounded-xl bg-white/5 p-3 items-center flex-1 min-w-[80px]">
              <Text className="text-xl font-semibold text-foreground">
                {data.stats.total}
              </Text>
              <Text className="text-xs text-muted">Total</Text>
            </View>
            <View className="rounded-xl bg-white/5 p-3 items-center flex-1 min-w-[80px]">
              <Text className="text-xl font-semibold text-green-500">
                {data.stats.completed}
              </Text>
              <Text className="text-xs text-muted">Done</Text>
            </View>
            <View className="rounded-xl bg-white/5 p-3 items-center flex-1 min-w-[80px]">
              <Text className="text-xl font-semibold text-muted">
                {data.stats.pending}
              </Text>
              <Text className="text-xs text-muted">Pending</Text>
            </View>
          </View>
          {(data.stats.overdue ?? 0) > 0 && (
            <View className="flex-row flex-wrap gap-2 mt-2">
              <View className="rounded-xl bg-white/5 p-3 items-center flex-1 min-w-[80px]">
                <Text className="text-xl font-semibold text-red-500">
                  {data.stats.overdue}
                </Text>
                <Text className="text-xs text-muted">Overdue</Text>
              </View>
              {(data.stats.today ?? 0) > 0 && (
                <View className="rounded-xl bg-white/5 p-3 items-center flex-1 min-w-[80px]">
                  <Text className="text-xl font-semibold text-primary">
                    {data.stats.today}
                  </Text>
                  <Text className="text-xs text-muted">Today</Text>
                </View>
              )}
              {(data.stats.upcoming ?? 0) > 0 && (
                <View className="rounded-xl bg-white/5 p-3 items-center flex-1 min-w-[80px]">
                  <Text className="text-xl font-semibold text-purple-500">
                    {data.stats.upcoming}
                  </Text>
                  <Text className="text-xs text-muted">Soon</Text>
                </View>
              )}
            </View>
          )}
        </Card.Body>
      </Card>
    );
  }

  // Projects View
  if (data.projects && data.projects.length > 0 && !data.todos) {
    const totalTasks = data.projects.reduce(
      (sum, p) => sum + (p.todo_count ?? 0),
      0,
    );
    const avgCompletion =
      data.projects.length > 0
        ? Math.round(
            data.projects.reduce(
              (sum, p) => sum + (p.completion_percentage ?? 0),
              0,
            ) / data.projects.length,
          )
        : 0;

    return (
      <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
        <Card.Body className="py-3 px-4">
          <View className="flex-row items-center justify-between mb-3">
            <Text className="text-sm text-foreground">Your Projects</Text>
            <View className="flex-row items-center gap-2">
              {totalTasks > 0 && (
                <Text className="text-xs text-muted">{totalTasks} tasks</Text>
              )}
              {avgCompletion > 0 && (
                <Text className="text-xs text-green-500">
                  {avgCompletion}% done
                </Text>
              )}
            </View>
          </View>
          {data.projects.map((project) => (
            <View
              key={project.id || project.name}
              className="rounded-xl bg-white/5 border border-white/8 p-3 mb-2 flex-row items-center justify-between"
            >
              <View className="flex-row items-center gap-3 flex-1">
                {project.color ? (
                  <View
                    className="w-3 h-3 rounded-full"
                    style={{ backgroundColor: project.color }}
                  />
                ) : (
                  <AppIcon
                    icon={FolderIcon}
                    size={12}
                    color="#71717a"
                    strokeWidth={1.5}
                  />
                )}
                <Text className="text-sm font-medium text-foreground flex-1">
                  {project.name}
                </Text>
              </View>
              <View className="flex-row items-center gap-2">
                {project.todo_count !== undefined && (
                  <Text className="text-xs text-muted">
                    {project.todo_count} tasks
                  </Text>
                )}
                {project.completion_percentage !== undefined && (
                  <Text
                    className={`text-xs font-medium ${
                      project.completion_percentage >= 80
                        ? "text-green-500"
                        : project.completion_percentage >= 40
                          ? "text-primary"
                          : "text-muted"
                    }`}
                  >
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

  // Todos List View
  if (data.todos && data.todos.length > 0) {
    const actionLabel =
      data.action === "search"
        ? "Search Results"
        : data.action === "create"
          ? "New Task"
          : data.action === "update"
            ? "Updated Tasks"
            : "Tasks";

    const completedCount = data.todos.filter((t) => isTodoDone(t)).length;
    const totalCount = data.todos.length;

    return (
      <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
        <Card.Body className="py-3 px-4">
          <View className="flex-row items-center justify-between mb-3">
            <Text className="text-sm text-foreground">{actionLabel}</Text>
            <View className="flex-row items-center gap-2">
              {completedCount > 0 ? (
                <Text className="text-xs text-green-500">
                  {completedCount}/{totalCount} done
                </Text>
              ) : (
                <Text className="text-xs text-muted">
                  {totalCount} {totalCount === 1 ? "task" : "tasks"}
                </Text>
              )}
            </View>
          </View>

          {data.todos.map((todo) => {
            const done = isTodoDone(todo);
            const status = getTodoStatus(todo);

            return (
              <View
                key={todo.id || todo.title}
                className="rounded-xl bg-white/5 border border-white/8 p-3 mb-2"
              >
                <View className="flex-row items-start gap-3">
                  <TodoCheckbox todo={todo} />

                  <View className="flex-1">
                    <View className="flex-row items-start justify-between gap-2">
                      <Text
                        className={`text-sm font-medium flex-1 ${
                          done ? "text-muted line-through" : "text-foreground"
                        }`}
                      >
                        {todo.title}
                      </Text>
                      {status !== "pending" && <StatusBadge status={status} />}
                    </View>

                    {/* Metadata row */}
                    <View className="flex-row flex-wrap items-center gap-2 mt-2">
                      {todo.priority &&
                        todo.priority !== "none" &&
                        priorityConfig[todo.priority] && (
                          <View
                            className={`rounded-full px-2 py-0.5 flex-row items-center gap-1 ${priorityConfig[todo.priority].bgColor}`}
                          >
                            <AppIcon
                              icon={Flag02Icon}
                              size={10}
                              color={priorityConfig[todo.priority].iconColor}
                              strokeWidth={1.5}
                            />
                            <Text
                              className={`text-xs ${priorityConfig[todo.priority].textColor}`}
                            >
                              {priorityConfig[todo.priority].label}
                            </Text>
                          </View>
                        )}

                      {todo.due_date && (
                        <View
                          className={`rounded-full px-2 py-0.5 flex-row items-center gap-1 ${
                            !done && isOverdue(todo.due_date)
                              ? "bg-red-500/10"
                              : "bg-white/5"
                          }`}
                        >
                          <AppIcon
                            icon={Calendar03Icon}
                            size={10}
                            color={
                              !done && isOverdue(todo.due_date)
                                ? "#ef4444"
                                : "#71717a"
                            }
                            strokeWidth={1.5}
                          />
                          <Text
                            className={`text-xs ${
                              !done && isOverdue(todo.due_date)
                                ? "text-red-500"
                                : "text-muted"
                            }`}
                          >
                            {formatDueDate(todo.due_date)}
                          </Text>
                        </View>
                      )}

                      {todo.project?.name && (
                        <View className="rounded-full bg-white/5 px-2 py-0.5 flex-row items-center gap-1">
                          {todo.project.color ? (
                            <View
                              className="w-2 h-2 rounded-full"
                              style={{ backgroundColor: todo.project.color }}
                            />
                          ) : (
                            <AppIcon
                              icon={FolderIcon}
                              size={10}
                              color="#71717a"
                              strokeWidth={1.5}
                            />
                          )}
                          <Text className="text-xs text-muted">
                            {todo.project.name}
                          </Text>
                        </View>
                      )}

                      {todo.labels?.map((label) => (
                        <View
                          key={label}
                          className="rounded-full bg-white/5 px-2 py-0.5 flex-row items-center gap-1"
                        >
                          <AppIcon
                            icon={LayoutGridIcon}
                            size={10}
                            color="#71717a"
                            strokeWidth={1.5}
                          />
                          <Text className="text-xs text-muted">{label}</Text>
                        </View>
                      ))}

                      {todo.subtasks && todo.subtasks.length > 0 && (
                        <View className="rounded-full bg-white/5 px-2 py-0.5">
                          <Text className="text-xs text-muted">
                            {todo.subtasks.filter((s) => s.completed).length}/
                            {todo.subtasks.length} subtasks
                          </Text>
                        </View>
                      )}
                    </View>
                  </View>
                </View>
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

  // Empty state
  if (data.action === "list" && (!data.todos || data.todos.length === 0)) {
    return (
      <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
        <Card.Body className="py-6 px-4 items-center gap-2">
          <AppIcon
            icon={CheckmarkCircle02Icon}
            size={28}
            color="#3f3f46"
            strokeWidth={1.5}
          />
          <Text className="text-sm text-foreground">No tasks found</Text>
          {data.message && (
            <Text className="text-xs text-muted">{data.message}</Text>
          )}
        </Card.Body>
      </Card>
    );
  }

  // Success/Action Message
  if (data.message && !data.todos && !data.stats && !data.projects) {
    const isDeleteAction = data.action === "delete";

    return (
      <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
        <Card.Body className="py-3 px-4">
          <View className="flex-row items-center gap-2">
            <Text
              className={`text-xs ${isDeleteAction ? "text-red-500" : "text-green-500"}`}
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

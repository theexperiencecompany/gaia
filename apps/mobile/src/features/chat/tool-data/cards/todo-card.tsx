import type {
  TodoAction,
  TodoToolData as TodoData,
  TodoItem,
  TodoPriority,
  TodoProject,
  TodoToolStats as TodoStats,
  TodoSubtask,
} from "@gaia/shared";
import { useState } from "react";
import { View } from "react-native";
import {
  AppIcon,
  ArrowRight01Icon,
  Calendar03Icon,
  CheckListIcon,
  CheckmarkCircle02Icon,
  Flag02Icon,
  Folder02Icon,
  Tag01Icon,
  Tick02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  ToolCardHeader,
  ToolCardInner,
  ToolCardShell,
} from "@/features/chat/tool-data/primitives";

export type {
  TodoAction,
  TodoData,
  TodoItem,
  TodoPriority,
  TodoProject,
  TodoStats,
  TodoSubtask,
};

// -- Priority meta -----------------------------------------------------------

const PRIORITY_META: Record<
  Exclude<TodoPriority, "none">,
  { color: string; bg: string }
> = {
  high: { color: "#ef4444", bg: "rgba(239, 68, 68, 0.1)" },
  medium: { color: "#eab308", bg: "rgba(234, 179, 8, 0.1)" },
  low: { color: "#3b82f6", bg: "rgba(59, 130, 246, 0.1)" },
};

// -- Helpers -----------------------------------------------------------------

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

function getListTitle(action: TodoAction): string {
  switch (action) {
    case "search":
      return "Search Results";
    case "create":
      return "New Task";
    case "update":
      return "Updated Tasks";
    case "delete":
      return "Deleted Tasks";
    default:
      return "Tasks";
  }
}

// -- Stat cell ---------------------------------------------------------------

function StatCell({
  value,
  label,
  color,
}: {
  value: number;
  label: string;
  color?: string;
}) {
  return (
    <ToolCardInner dense className="flex-1 items-center">
      <Text
        className="text-xl font-semibold"
        style={color ? { color } : undefined}
      >
        {value}
      </Text>
      <Text className="text-xs text-zinc-500 mt-0.5">{label}</Text>
    </ToolCardInner>
  );
}

// -- Todo row ----------------------------------------------------------------

function TodoItemRow({ todo }: { todo: TodoItem }) {
  const [expanded, setExpanded] = useState(false);

  const dueInfo = todo.due_date ? formatDueDate(todo.due_date) : null;
  const priorityMeta =
    todo.priority !== "none" ? PRIORITY_META[todo.priority] : null;
  const hasDescription = Boolean(todo.description);
  const hasLabels = todo.labels.length > 0;
  const hasSubtasks = todo.subtasks.length > 0;
  const hasExpandable = hasDescription || hasSubtasks;

  const completedSubtasks = todo.subtasks.filter((s) => s.completed).length;

  return (
    <ToolCardInner
      onPress={hasExpandable ? () => setExpanded((v) => !v) : undefined}
    >
      {/* Title row */}
      <View className="flex-row items-start gap-3">
        {/* Checkbox */}
        <View
          className={`mt-0.5 w-4 h-4 shrink-0 rounded-full border-2 items-center justify-center ${
            todo.completed ? "border-green-500 bg-green-500" : "border-zinc-600"
          }`}
        >
          {todo.completed && (
            <AppIcon icon={Tick02Icon} size={10} color="#ffffff" />
          )}
        </View>

        {/* Title + expand arrow */}
        <View className="flex-1 flex-row items-start justify-between gap-2">
          <Text
            className={`flex-1 text-sm font-medium ${
              todo.completed ? "text-zinc-500 line-through" : "text-zinc-100"
            }`}
            numberOfLines={expanded ? 0 : 1}
          >
            {todo.title}
          </Text>
          {hasExpandable && (
            <View
              style={{
                transform: [{ rotate: expanded ? "90deg" : "0deg" }],
              }}
            >
              <AppIcon icon={ArrowRight01Icon} size={16} color="#71717a" />
            </View>
          )}
        </View>
      </View>

      {/* Metadata row */}
      {(priorityMeta ||
        dueInfo ||
        todo.project ||
        hasLabels ||
        hasSubtasks) && (
        <View className="flex-row flex-wrap items-center gap-2 mt-2 pl-7">
          {priorityMeta && (
            <View
              className="flex-row items-center gap-1 px-2 py-0.5 rounded-full"
              style={{ backgroundColor: priorityMeta.bg }}
            >
              <AppIcon icon={Flag02Icon} size={10} color={priorityMeta.color} />
              <Text className="text-xs" style={{ color: priorityMeta.color }}>
                {todo.priority}
              </Text>
            </View>
          )}

          {dueInfo && (
            <View
              className="flex-row items-center gap-1 px-2 py-0.5 rounded-full"
              style={
                dueInfo.isOverdue
                  ? { backgroundColor: "rgba(239, 68, 68, 0.1)" }
                  : dueInfo.isToday
                    ? { backgroundColor: "rgba(245, 158, 11, 0.1)" }
                    : { backgroundColor: "rgba(161, 161, 170, 0.1)" }
              }
            >
              <AppIcon
                icon={Calendar03Icon}
                size={10}
                color={
                  dueInfo.isOverdue
                    ? "#ef4444"
                    : dueInfo.isToday
                      ? "#f59e0b"
                      : "#a1a1aa"
                }
              />
              <Text
                className="text-xs"
                style={{
                  color: dueInfo.isOverdue
                    ? "#ef4444"
                    : dueInfo.isToday
                      ? "#f59e0b"
                      : "#a1a1aa",
                }}
              >
                {dueInfo.label}
              </Text>
            </View>
          )}

          {todo.project && (
            <View className="flex-row items-center gap-1 px-2 py-0.5 rounded-full bg-zinc-800">
              {todo.project.color ? (
                <View
                  className="h-2 w-2 rounded-full"
                  style={{ backgroundColor: todo.project.color }}
                />
              ) : (
                <AppIcon icon={Folder02Icon} size={10} color="#71717a" />
              )}
              <Text className="text-xs text-zinc-400" numberOfLines={1}>
                {todo.project.name}
              </Text>
            </View>
          )}

          {todo.labels.map((label) => (
            <View
              key={label}
              className="flex-row items-center gap-1 px-2 py-0.5 rounded-full bg-zinc-800"
            >
              <AppIcon icon={Tag01Icon} size={10} color="#71717a" />
              <Text className="text-xs text-zinc-400">{label}</Text>
            </View>
          ))}

          {hasSubtasks && (
            <View className="px-2 py-0.5 rounded-full bg-zinc-800">
              <Text className="text-xs text-zinc-400">
                {completedSubtasks}/{todo.subtasks.length} subtasks
              </Text>
            </View>
          )}
        </View>
      )}

      {/* Expanded content */}
      {expanded && hasExpandable && (
        <View className="mt-3 gap-3 pl-7">
          {hasDescription && (
            <Text className="text-sm text-zinc-400">{todo.description}</Text>
          )}

          {hasSubtasks && (
            <View className="gap-1">
              <Text className="text-xs font-medium text-zinc-500">
                Subtasks
              </Text>
              {todo.subtasks.map((subtask) => (
                <View
                  key={subtask.id}
                  className="flex-row items-center gap-2 pl-2"
                >
                  <View
                    className={`w-4 h-4 rounded-full border-2 items-center justify-center ${
                      subtask.completed
                        ? "border-green-500 bg-green-500"
                        : "border-zinc-600"
                    }`}
                  >
                    {subtask.completed && (
                      <AppIcon icon={Tick02Icon} size={10} color="#ffffff" />
                    )}
                  </View>
                  <Text
                    className={`text-xs ${
                      subtask.completed
                        ? "text-zinc-500 line-through"
                        : "text-zinc-200"
                    }`}
                  >
                    {subtask.title}
                  </Text>
                </View>
              ))}
            </View>
          )}
        </View>
      )}
    </ToolCardInner>
  );
}

// -- Main card ---------------------------------------------------------------

export function TodoCard({ data }: { data: TodoData }) {
  const action = data.action ?? "list";

  // Stats view
  if (action === "stats" && data.stats) {
    const s = data.stats;
    return (
      <ToolCardShell>
        <ToolCardHeader icon={CheckListIcon} title="Task Overview" />
        <View className="flex-row gap-2">
          <StatCell value={s.total} label="Total" />
          <StatCell value={s.completed} label="Done" color="#22c55e" />
          <StatCell value={s.pending} label="Pending" color="#eab308" />
        </View>
        {(s.overdue > 0 || s.today > 0 || s.upcoming > 0) && (
          <View className="flex-row gap-2 mt-2">
            {s.overdue > 0 && (
              <StatCell value={s.overdue} label="Overdue" color="#ef4444" />
            )}
            {s.today > 0 && (
              <StatCell value={s.today} label="Today" color="#3b82f6" />
            )}
            {s.upcoming > 0 && (
              <StatCell value={s.upcoming} label="Soon" color="#a855f7" />
            )}
          </View>
        )}
      </ToolCardShell>
    );
  }

  // Projects view
  if (data.projects && data.projects.length > 0 && !data.todos) {
    return (
      <ToolCardShell>
        <ToolCardHeader
          icon={CheckListIcon}
          title="Your Projects"
          count={data.projects.length}
        />
        <View className="gap-2">
          {data.projects.map((project) => (
            <ToolCardInner key={project.id}>
              <View className="flex-row items-center justify-between">
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
                <View className="flex-row items-center gap-2">
                  {project.todo_count !== undefined && (
                    <Text className="text-xs text-zinc-500">
                      {project.todo_count} tasks
                    </Text>
                  )}
                  {project.completion_percentage !== undefined && (
                    <Text className="text-xs text-zinc-500">
                      {"· "}
                      {Math.round(project.completion_percentage)}%
                    </Text>
                  )}
                </View>
              </View>
            </ToolCardInner>
          ))}
        </View>
      </ToolCardShell>
    );
  }

  // Todos list view
  if (data.todos && data.todos.length > 0) {
    return (
      <ToolCardShell>
        <ToolCardHeader
          icon={CheckListIcon}
          title={getListTitle(action)}
          count={data.todos.length}
        />
        <View className="gap-2">
          {data.todos.map((todo) => (
            <TodoItemRow key={todo.id} todo={todo} />
          ))}
        </View>
        {data.message && (
          <Text className="text-xs text-zinc-500 mt-3">{data.message}</Text>
        )}
      </ToolCardShell>
    );
  }

  // Empty state for list action
  if (action === "list" && (!data.todos || data.todos.length === 0)) {
    return (
      <ToolCardShell>
        <View className="items-center py-2">
          <AppIcon icon={CheckmarkCircle02Icon} size={32} color="#52525b" />
          <Text className="mt-2 text-sm text-zinc-200">No tasks found</Text>
          {data.message && (
            <Text className="text-xs text-zinc-500 mt-1">{data.message}</Text>
          )}
        </View>
      </ToolCardShell>
    );
  }

  // Action message (delete/success with no todos)
  if (data.message && !data.todos && !data.stats && !data.projects) {
    const isDelete = action === "delete";
    return (
      <ToolCardShell>
        <View className="flex-row items-center gap-2">
          <AppIcon
            icon={CheckmarkCircle02Icon}
            size={16}
            color={isDelete ? "#ef4444" : "#22c55e"}
          />
          <Text className="text-sm text-zinc-100 flex-1">{data.message}</Text>
        </View>
      </ToolCardShell>
    );
  }

  return null;
}

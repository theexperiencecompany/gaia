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
import { AppIcon, CheckListIcon, Flag02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  SectionLabel,
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
  medium: { color: "#f59e0b", bg: "rgba(245, 158, 11, 0.1)" },
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
        className="text-2xl font-semibold"
        style={color ? { color } : undefined}
      >
        {value}
      </Text>
      <View className="mt-1">
        <SectionLabel>{label}</SectionLabel>
      </View>
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
  const hasExpandable = hasDescription || hasLabels || hasSubtasks;

  return (
    <ToolCardInner
      dense
      onPress={hasExpandable ? () => setExpanded((v) => !v) : undefined}
    >
      <View className="flex-row items-center gap-3">
        <View
          className={`w-5 h-5 rounded-full ${
            todo.completed ? "bg-emerald-500" : "bg-zinc-700"
          }`}
        />
        <Text
          className={`flex-1 text-sm font-medium ${
            todo.completed ? "text-zinc-500 line-through" : "text-zinc-100"
          }`}
          numberOfLines={expanded ? 0 : 1}
        >
          {todo.title}
        </Text>
        {priorityMeta && (
          <View
            className="flex-row items-center gap-1 px-2 py-0.5 rounded-full"
            style={{ backgroundColor: priorityMeta.bg }}
          >
            <AppIcon icon={Flag02Icon} size={10} color={priorityMeta.color} />
            <Text
              className="text-[10px] font-semibold uppercase"
              style={{ color: priorityMeta.color }}
            >
              {todo.priority}
            </Text>
          </View>
        )}
      </View>

      {(dueInfo || todo.project) && (
        <View className="flex-row flex-wrap items-center gap-1.5 mt-2 pl-8">
          {dueInfo && (
            <View
              className="px-2 py-0.5 rounded-full"
              style={
                dueInfo.isOverdue
                  ? { backgroundColor: "rgba(239, 68, 68, 0.1)" }
                  : dueInfo.isToday
                    ? { backgroundColor: "rgba(245, 158, 11, 0.1)" }
                    : undefined
              }
            >
              <Text
                className="text-[10px] font-medium"
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
            <View className="flex-row items-center gap-1 px-2 py-0.5 rounded-full bg-zinc-700">
              {todo.project.color ? (
                <View
                  className="h-2 w-2 rounded-full"
                  style={{ backgroundColor: todo.project.color }}
                />
              ) : null}
              <Text
                className="text-[10px] text-zinc-300 font-medium"
                numberOfLines={1}
              >
                {todo.project.name}
              </Text>
            </View>
          )}
        </View>
      )}

      {expanded && hasExpandable && (
        <View className="mt-2 gap-2 pl-8">
          {hasDescription && (
            <Text className="text-zinc-400 text-xs">{todo.description}</Text>
          )}
          {hasLabels && (
            <View className="flex-row flex-wrap gap-1">
              {todo.labels.map((label) => (
                <View
                  key={label}
                  className="bg-zinc-700 px-2 py-0.5 rounded-full"
                >
                  <Text className="text-zinc-300 text-[10px]">{label}</Text>
                </View>
              ))}
            </View>
          )}
          {hasSubtasks && (
            <View className="gap-1">
              <SectionLabel>SUBTASKS</SectionLabel>
              {todo.subtasks.map((subtask) => (
                <Text
                  key={subtask.id}
                  className={`text-xs ${
                    subtask.completed
                      ? "text-zinc-500 line-through"
                      : "text-zinc-400"
                  }`}
                >
                  {"· "}
                  {subtask.title}
                </Text>
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
        <ToolCardHeader icon={CheckListIcon} title="Stats" />
        <View className="flex-row gap-2">
          <StatCell value={s.total} label="TOTAL" />
          <StatCell value={s.completed} label="DONE" color="#10b981" />
          <StatCell value={s.pending} label="PENDING" color="#f59e0b" />
        </View>
        {(s.overdue > 0 || s.today > 0 || s.upcoming > 0) && (
          <View className="flex-row gap-2 mt-2">
            {s.overdue > 0 && (
              <StatCell value={s.overdue} label="OVERDUE" color="#ef4444" />
            )}
            {s.today > 0 && (
              <StatCell value={s.today} label="TODAY" color="#3b82f6" />
            )}
            {s.upcoming > 0 && (
              <StatCell value={s.upcoming} label="SOON" color="#a855f7" />
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
          title="Projects"
          count={data.projects.length}
        />
        <View className="gap-1.5">
          {data.projects.map((project) => (
            <ToolCardInner key={project.id} dense>
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
        <View className="gap-1.5">
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
        <ToolCardHeader icon={CheckListIcon} title="Tasks" />
        <Text className="text-zinc-300 text-sm">No tasks found</Text>
        {data.message && (
          <Text className="text-xs text-zinc-500 mt-1">{data.message}</Text>
        )}
      </ToolCardShell>
    );
  }

  // Action message (delete/success with no todos)
  if (data.message && !data.todos && !data.stats && !data.projects) {
    const isDelete = action === "delete";
    return (
      <ToolCardShell>
        <View className="flex-row items-center gap-2">
          <View
            className="w-5 h-5 rounded-full items-center justify-center"
            style={{
              backgroundColor: isDelete
                ? "rgba(239, 68, 68, 0.15)"
                : "rgba(16, 185, 129, 0.15)",
            }}
          >
            <Text
              className="text-[10px] font-semibold"
              style={{ color: isDelete ? "#ef4444" : "#10b981" }}
            >
              {isDelete ? "–" : "+"}
            </Text>
          </View>
          <Text className="text-sm text-zinc-100 flex-1">{data.message}</Text>
        </View>
      </ToolCardShell>
    );
  }

  return null;
}

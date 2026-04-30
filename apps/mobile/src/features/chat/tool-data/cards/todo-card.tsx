import { useState } from "react";
import { Pressable, View } from "react-native";
import {
  AppIcon,
  ArrowRight01Icon,
  Calendar03Icon,
  CheckmarkCircle02Icon,
  Flag02Icon,
  Folder02Icon,
  PlayIcon,
  Tag01Icon,
  Tick02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  ToolCardHeader,
  ToolCardInner,
  ToolCardShell,
} from "@/features/chat/tool-data/primitives";

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

export interface TodoWorkflowStep {
  id: string;
  title: string;
  description: string;
  category: string;
}

export interface TodoWorkflow {
  id: string;
  steps: TodoWorkflowStep[];
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
  workflow?: TodoWorkflow;
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

// Priority: urgent=red (not in enum but mapped to high), high=orange,
// medium=yellow-500 (#eab308), low=zinc. Web maps HIGH->red, MEDIUM->yellow,
// LOW->blue — mobile matches the stricter contract: high=orange, med=yellow,
// low=zinc. "none" renders no pill.
const PRIORITY_STYLE: Record<
  Exclude<TodoPriority, "none">,
  { bg: string; text: string; icon: string }
> = {
  high: {
    bg: "bg-orange-500/10",
    text: "text-orange-400",
    icon: "#fb923c",
  },
  medium: {
    bg: "bg-yellow-500/10",
    text: "text-yellow-500",
    icon: "#eab308",
  },
  low: {
    bg: "bg-zinc-800",
    text: "text-zinc-400",
    icon: "#a1a1aa",
  },
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

function Checkbox({ checked }: { checked: boolean }) {
  return (
    <View
      className={`mt-0.5 h-4 w-4 shrink-0 rounded-full items-center justify-center ${
        checked ? "border-green-500 bg-green-500" : "bg-zinc-800"
      }`}
      style={
        checked
          ? undefined
          : { borderWidth: 2, borderColor: "#52525b" /* zinc-600 */ }
      }
    >
      {checked ? <AppIcon icon={Tick02Icon} size={10} color="#ffffff" /> : null}
    </View>
  );
}

function DuePill({
  label,
  isOverdue,
  isToday,
}: {
  label: string;
  isOverdue: boolean;
  isToday: boolean;
}) {
  const style = isOverdue
    ? { bg: "bg-red-500/10", text: "text-red-500", icon: "#ef4444" }
    : isToday
      ? { bg: "bg-blue-500/10", text: "text-blue-500", icon: "#3b82f6" }
      : { bg: "bg-zinc-800", text: "text-zinc-400", icon: "#a1a1aa" };

  return (
    <View
      className={`flex-row items-center gap-1 rounded-full px-2 py-0.5 ${style.bg}`}
    >
      <AppIcon icon={Calendar03Icon} size={10} color={style.icon} />
      <Text className={`text-[11px] ${style.text}`}>{label}</Text>
    </View>
  );
}

function PriorityPill({
  priority,
}: {
  priority: Exclude<TodoPriority, "none">;
}) {
  const s = PRIORITY_STYLE[priority];
  return (
    <View
      className={`flex-row items-center gap-1 rounded-full px-2 py-0.5 ${s.bg}`}
    >
      <AppIcon icon={Flag02Icon} size={10} color={s.icon} />
      <Text className={`text-[11px] capitalize ${s.text}`}>{priority}</Text>
    </View>
  );
}

function MetaPill({
  children,
  leading,
}: {
  children: React.ReactNode;
  leading?: React.ReactNode;
}) {
  return (
    <View className="flex-row items-center gap-1 rounded-full bg-zinc-800 px-2 py-0.5">
      {leading}
      <Text className="text-[11px] text-zinc-400">{children}</Text>
    </View>
  );
}

function TodoItemRow({ todo }: { todo: TodoItem }) {
  const [expanded, setExpanded] = useState(false);
  const completedSubtasks = todo.subtasks.filter((s) => s.completed).length;
  const totalSubtasks = todo.subtasks.length;
  const dueInfo = todo.due_date ? formatDueDate(todo.due_date) : null;
  const hasDetails =
    Boolean(todo.description) || totalSubtasks > 0 || Boolean(todo.workflow);

  return (
    <ToolCardInner className="mb-2">
      <View className="flex-row items-start gap-3">
        <Checkbox checked={todo.completed} />

        <View className="flex-1">
          <View className="flex-row items-start justify-between gap-2">
            <Text
              className={`flex-1 text-sm font-medium ${
                todo.completed ? "text-zinc-500 line-through" : "text-zinc-100"
              }`}
              numberOfLines={2}
            >
              {todo.title}
            </Text>

            {hasDetails ? (
              <Pressable
                onPress={() => setExpanded((v) => !v)}
                className="p-1 -m-1 rounded"
                hitSlop={8}
              >
                <View
                  style={{
                    transform: [{ rotate: expanded ? "90deg" : "0deg" }],
                  }}
                >
                  <AppIcon icon={ArrowRight01Icon} size={14} color="#71717a" />
                </View>
              </Pressable>
            ) : null}
          </View>

          <View className="mt-2 flex-row flex-wrap items-center gap-1.5">
            {todo.priority !== "none" ? (
              <PriorityPill priority={todo.priority} />
            ) : null}

            {dueInfo ? (
              <DuePill
                label={dueInfo.label}
                isOverdue={dueInfo.isOverdue}
                isToday={dueInfo.isToday}
              />
            ) : null}

            {todo.project ? (
              <MetaPill
                leading={
                  todo.project.color ? (
                    <View
                      className="h-2 w-2 rounded-full"
                      style={{ backgroundColor: todo.project.color }}
                    />
                  ) : (
                    <AppIcon icon={Folder02Icon} size={10} color="#a1a1aa" />
                  )
                }
              >
                {todo.project.name}
              </MetaPill>
            ) : null}

            {todo.labels.map((label) => (
              <MetaPill
                key={label}
                leading={<AppIcon icon={Tag01Icon} size={10} color="#a1a1aa" />}
              >
                {label}
              </MetaPill>
            ))}

            {totalSubtasks > 0 ? (
              <MetaPill>
                {completedSubtasks}/{totalSubtasks} subtasks
              </MetaPill>
            ) : null}
          </View>

          {expanded ? (
            <View className="mt-3 gap-3">
              {todo.description ? (
                <Text className="text-sm text-zinc-400">
                  {todo.description}
                </Text>
              ) : null}

              {totalSubtasks > 0 ? (
                <View className="gap-1">
                  <Text className="text-xs font-medium text-zinc-500">
                    Subtasks
                  </Text>
                  {todo.subtasks.map((subtask) => (
                    <View
                      key={subtask.id}
                      className="flex-row items-center gap-2 pl-1"
                    >
                      <Checkbox checked={subtask.completed} />
                      <Text
                        className={`text-xs ${
                          subtask.completed
                            ? "text-zinc-500 line-through"
                            : "text-zinc-300"
                        }`}
                      >
                        {subtask.title}
                      </Text>
                    </View>
                  ))}
                </View>
              ) : null}

              {todo.workflow ? (
                <View className="gap-2">
                  <Text className="text-xs font-medium text-zinc-500">
                    Workflow ({todo.workflow.steps.length} steps)
                  </Text>
                  <View className="flex-row">
                    <View className="flex-row items-center gap-1 rounded-full bg-green-500/20 px-3 py-1">
                      <AppIcon icon={PlayIcon} size={10} color="#4ade80" />
                      <Text className="text-xs text-green-400">
                        Run Workflow
                      </Text>
                    </View>
                  </View>
                </View>
              ) : null}
            </View>
          ) : null}
        </View>
      </View>
    </ToolCardInner>
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
    <View className="flex-1 rounded-2xl bg-zinc-900 p-3 items-center">
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
      <ToolCardShell>
        <ToolCardHeader title="Task Overview" />
        <View className="flex-row gap-2 mb-2">
          <StatBox value={s.total} label="Total" color="text-zinc-100" />
          <StatBox value={s.completed} label="Done" color="text-green-500" />
          <StatBox value={s.pending} label="Pending" color="text-yellow-500" />
        </View>
        {s.overdue > 0 || s.today > 0 || s.upcoming > 0 ? (
          <View className="flex-row gap-2">
            {s.overdue > 0 ? (
              <StatBox value={s.overdue} label="Overdue" color="text-red-500" />
            ) : null}
            {s.today > 0 ? (
              <StatBox value={s.today} label="Today" color="text-blue-500" />
            ) : null}
            {s.upcoming > 0 ? (
              <StatBox
                value={s.upcoming}
                label="Soon"
                color="text-purple-500"
              />
            ) : null}
          </View>
        ) : null}
      </ToolCardShell>
    );
  }

  // Projects view
  if (data.projects && data.projects.length > 0 && !data.todos) {
    return (
      <ToolCardShell>
        <ToolCardHeader title="Your Projects" />
        {data.projects.map((project) => (
          <ToolCardInner key={project.id} className="mb-2">
            <View className="flex-row items-center justify-between">
              <View className="flex-row items-center gap-3 flex-1">
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
                {project.todo_count !== undefined ? (
                  <Text className="text-xs text-zinc-500">
                    {project.todo_count} tasks
                  </Text>
                ) : null}
                {project.completion_percentage !== undefined ? (
                  <Text className="text-xs text-zinc-500">
                    {Math.round(project.completion_percentage)}%
                  </Text>
                ) : null}
              </View>
            </View>
          </ToolCardInner>
        ))}
      </ToolCardShell>
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
      <ToolCardShell>
        <ToolCardHeader
          title={headerLabel}
          trailing={
            <Text className="text-xs text-zinc-500">
              {data.todos.length} {data.todos.length === 1 ? "task" : "tasks"}
            </Text>
          }
        />
        {data.todos.map((todo) => (
          <TodoItemRow key={todo.id} todo={todo} />
        ))}
        {data.message ? (
          <Text className="text-xs text-zinc-500 mt-1">{data.message}</Text>
        ) : null}
      </ToolCardShell>
    );
  }

  // Empty state for list action
  if (action === "list" && (!data.todos || data.todos.length === 0)) {
    return (
      <ToolCardShell>
        <View className="items-center py-2">
          <AppIcon icon={CheckmarkCircle02Icon} size={32} color="#52525b" />
          <Text className="mt-2 text-sm text-zinc-300">No tasks found</Text>
          {data.message ? (
            <Text className="mt-1 text-xs text-zinc-500">{data.message}</Text>
          ) : null}
        </View>
      </ToolCardShell>
    );
  }

  // Action message with no todos
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

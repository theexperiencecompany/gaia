import { FlashList } from "@shopify/flash-list";
import { useCallback, useMemo } from "react";
import { RefreshControl, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Text } from "@/components/ui/text";
import type {
  FilterTab,
  Project,
  SortOption,
  Todo,
} from "../../types/todo-types";
import { TodoRow } from "../row/todo-row";
import { TodoEmptyState } from "./todo-empty-state";
import { TodoListSkeleton } from "./todo-list-skeleton";

interface TodoSectionListProps {
  todos: Todo[];
  projects: Project[];
  filter: FilterTab;
  isLoading: boolean;
  isRefreshing: boolean;
  isSearchEmpty: boolean;
  onRefresh: () => void;
  onToggleComplete: (todo: Todo) => void;
  onTodoPress: (todo: Todo) => void;
  onTodoDelete: (todo: Todo) => void;
  onTodoSnooze: (todo: Todo) => void;
  onTodoLongPress: (todo: Todo) => void;
  onTodoOpenMenu: (todo: Todo) => void;
  onAddTodo: () => void;
  selectionMode: boolean;
  selectedIds: Set<string>;
  onSelectTodo: (id: string) => void;
  activeSort: SortOption | null;
}

interface SectionRow {
  type: "section";
  id: string;
  label: string;
  count: number;
}
interface TodoListRow {
  type: "todo";
  id: string;
  todo: Todo;
}
type ListRow = SectionRow | TodoListRow;

const DAY_MS = 86_400_000;

function startOfDayMs(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

interface UpcomingBucket {
  key: "today" | "tomorrow" | "this-week" | "later";
  label: string;
  todos: Todo[];
}

function bucketUpcoming(todos: Todo[]): UpcomingBucket[] {
  const today = startOfDayMs(new Date());
  const buckets: Record<UpcomingBucket["key"], UpcomingBucket> = {
    today: { key: "today", label: "Today", todos: [] },
    tomorrow: { key: "tomorrow", label: "Tomorrow", todos: [] },
    "this-week": { key: "this-week", label: "This week", todos: [] },
    later: { key: "later", label: "Later", todos: [] },
  };

  for (const t of todos) {
    if (!t.due_date) {
      buckets.later.todos.push(t);
      continue;
    }
    const due = startOfDayMs(new Date(t.due_date));
    const diffDays = Math.round((due - today) / DAY_MS);
    if (diffDays <= 0) buckets.today.todos.push(t);
    else if (diffDays === 1) buckets.tomorrow.todos.push(t);
    else if (diffDays <= 7) buckets["this-week"].todos.push(t);
    else buckets.later.todos.push(t);
  }

  return Object.values(buckets).filter((b) => b.todos.length > 0);
}

function bucketByProject(
  todos: Todo[],
  projects: Project[],
): { id: string; label: string; todos: Todo[] }[] {
  const byProject = new Map<string, { label: string; todos: Todo[] }>();
  for (const t of todos) {
    const proj = projects.find((p) => p.id === t.project_id);
    const key = proj?.id ?? "__unassigned__";
    const label = proj?.name ?? "Inbox";
    const entry = byProject.get(key);
    if (entry) entry.todos.push(t);
    else byProject.set(key, { label, todos: [t] });
  }
  return Array.from(byProject.entries()).map(([id, value]) => ({
    id,
    label: value.label,
    todos: value.todos,
  }));
}

function getPriorityWeight(priority: string): number {
  switch (priority) {
    case "high":
      return 3;
    case "medium":
      return 2;
    case "low":
      return 1;
    default:
      return 0;
  }
}

function applySort(todos: Todo[], sort: SortOption | null): Todo[] {
  if (!sort) return todos;
  const dir = sort.direction === "asc" ? 1 : -1;
  const out = [...todos];
  out.sort((a, b) => {
    switch (sort.field) {
      case "title":
        return dir * a.title.localeCompare(b.title);
      case "priority":
        return (
          dir * (getPriorityWeight(a.priority) - getPriorityWeight(b.priority))
        );
      case "due_date": {
        const at = a.due_date ? new Date(a.due_date).getTime() : Infinity;
        const bt = b.due_date ? new Date(b.due_date).getTime() : Infinity;
        return dir * (at - bt);
      }
      default: {
        const at = a.created_at ? new Date(a.created_at).getTime() : 0;
        const bt = b.created_at ? new Date(b.created_at).getTime() : 0;
        return dir * (at - bt);
      }
    }
  });
  return out;
}

/**
 * FlashList-backed list with per-filter sectioning logic per spec §C:
 * - Today / Inbox / Overdue / Completed → single flat section.
 * - Upcoming → grouped Today / Tomorrow / This Week / Later.
 * - All → grouped by project.
 */
export function TodoSectionList({
  todos,
  projects,
  filter,
  isLoading,
  isRefreshing,
  isSearchEmpty,
  onRefresh,
  onToggleComplete,
  onTodoPress,
  onTodoDelete,
  onTodoSnooze,
  onTodoLongPress,
  onTodoOpenMenu,
  onAddTodo,
  selectionMode,
  selectedIds,
  onSelectTodo,
  activeSort,
}: TodoSectionListProps) {
  const insets = useSafeAreaInsets();

  const rows = useMemo<ListRow[]>(() => {
    const sorted = applySort(todos, activeSort);
    if (filter === "upcoming") {
      const buckets = bucketUpcoming(sorted);
      return buckets.flatMap<ListRow>((b) => [
        {
          type: "section",
          id: `section-${b.key}`,
          label: b.label,
          count: b.todos.length,
        },
        ...b.todos.map<ListRow>((t) => ({
          type: "todo",
          id: t.id,
          todo: t,
        })),
      ]);
    }
    if (filter === "all") {
      const buckets = bucketByProject(sorted, projects);
      return buckets.flatMap<ListRow>((b) => [
        {
          type: "section",
          id: `section-${b.id}`,
          label: b.label,
          count: b.todos.length,
        },
        ...b.todos.map<ListRow>((t) => ({
          type: "todo",
          id: t.id,
          todo: t,
        })),
      ]);
    }
    return sorted.map<ListRow>((t) => ({ type: "todo", id: t.id, todo: t }));
  }, [todos, activeSort, filter, projects]);

  const renderItem = useCallback(
    ({ item }: { item: ListRow }) => {
      if (item.type === "section") {
        return (
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: 8,
              paddingHorizontal: 16,
              paddingTop: 24,
              paddingBottom: 4,
            }}
          >
            <Text
              style={{
                fontSize: 11,
                fontWeight: "600",
                letterSpacing: 0.7,
                color: "#71717a",
                textTransform: "uppercase",
              }}
            >
              {item.label}
            </Text>
            <View
              style={{
                backgroundColor: "rgba(39,39,42,0.60)",
                borderRadius: 999,
                paddingHorizontal: 8,
                paddingVertical: 1,
              }}
            >
              <Text style={{ fontSize: 11, color: "#a1a1aa" }}>
                {item.count}
              </Text>
            </View>
          </View>
        );
      }
      const project = projects.find((p) => p.id === item.todo.project_id);
      return (
        <TodoRow
          todo={item.todo}
          project={project}
          onToggleComplete={onToggleComplete}
          onPress={onTodoPress}
          onDelete={onTodoDelete}
          onSnooze={onTodoSnooze}
          onLongPress={onTodoLongPress}
          onOpenMenu={onTodoOpenMenu}
          selectionMode={selectionMode}
          isSelected={selectedIds.has(item.todo.id)}
          onSelect={onSelectTodo}
        />
      );
    },
    [
      projects,
      onToggleComplete,
      onTodoPress,
      onTodoDelete,
      onTodoSnooze,
      onTodoLongPress,
      onTodoOpenMenu,
      selectionMode,
      selectedIds,
      onSelectTodo,
    ],
  );

  const keyExtractor = useCallback((item: ListRow) => item.id, []);

  if (isLoading && todos.length === 0) {
    return <TodoListSkeleton />;
  }

  if (todos.length === 0) {
    return (
      <TodoEmptyState
        filter={filter}
        isSearchEmpty={isSearchEmpty}
        onAddTodo={onAddTodo}
      />
    );
  }

  return (
    <FlashList
      data={rows}
      keyExtractor={keyExtractor}
      renderItem={renderItem}
      contentContainerStyle={{
        paddingBottom: selectionMode ? insets.bottom + 96 : insets.bottom + 24,
      }}
      refreshControl={
        <RefreshControl
          refreshing={isRefreshing}
          onRefresh={onRefresh}
          tintColor="#00bbff"
        />
      }
    />
  );
}

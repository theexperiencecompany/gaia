import type { Priority, Project, Todo } from "../types/todo";

export const TodoQueryKeys = {
  all: ["todos"] as const,
  list: (filters?: Record<string, unknown>) =>
    filters
      ? ([...TodoQueryKeys.all, "list", filters] as const)
      : ([...TodoQueryKeys.all, "list"] as const),
  detail: (id: string) => [...TodoQueryKeys.all, "detail", id] as const,
  counts: () => [...TodoQueryKeys.all, "counts"] as const,
  projects: () => [...TodoQueryKeys.all, "projects"] as const,
  project: (projectId: string) =>
    [...TodoQueryKeys.all, "projects", projectId] as const,
};

export interface TodoFilterState {
  status?: "all" | "active" | "completed";
  priority?: Priority | "all";
  labels?: string[];
  projectId?: string;
  search?: string;
  starred?: boolean;
  overdue?: boolean;
  dueToday?: boolean;
  dueThisWeek?: boolean;
}

export function filterTodos(todos: Todo[], filter: TodoFilterState): Todo[] {
  return todos.filter((todo) => {
    if (filter.status && filter.status !== "all") {
      if (filter.status === "completed" && !todo.completed) return false;
      if (filter.status === "active" && todo.completed) return false;
    }

    if (filter.priority && filter.priority !== "all") {
      if (todo.priority !== filter.priority) return false;
    }

    if (filter.labels && filter.labels.length > 0) {
      const hasLabel = filter.labels.some((label) =>
        todo.labels.includes(label),
      );
      if (!hasLabel) return false;
    }

    if (filter.projectId && todo.project_id !== filter.projectId) {
      return false;
    }

    if (filter.search) {
      const query = filter.search.toLowerCase();
      const matchesTitle = todo.title.toLowerCase().includes(query);
      const matchesDescription =
        todo.description?.toLowerCase().includes(query) ?? false;
      if (!matchesTitle && !matchesDescription) return false;
    }

    if (filter.starred !== undefined && todo.starred !== filter.starred) {
      return false;
    }

    if (filter.overdue && todo.due_date) {
      const isOverdue = new Date(todo.due_date) < new Date() && !todo.completed;
      if (!isOverdue) return false;
    }

    if (filter.dueToday && todo.due_date) {
      const today = new Date();
      const dueDate = new Date(todo.due_date);
      const isSameDay =
        dueDate.getFullYear() === today.getFullYear() &&
        dueDate.getMonth() === today.getMonth() &&
        dueDate.getDate() === today.getDate();
      if (!isSameDay) return false;
    }

    if (filter.dueThisWeek && todo.due_date) {
      const today = new Date();
      const weekFromNow = new Date(today);
      weekFromNow.setDate(today.getDate() + 7);
      const dueDate = new Date(todo.due_date);
      if (dueDate < today || dueDate > weekFromNow) return false;
    }

    return true;
  });
}

const PRIORITY_ORDER: Record<Priority, number> = {
  high: 0,
  medium: 1,
  low: 2,
  none: 3,
};

export function sortTodos(todos: Todo[], sortBy: string): Todo[] {
  const sorted = [...todos];

  switch (sortBy) {
    case "priority_asc":
      return sorted.sort(
        (a, b) => PRIORITY_ORDER[a.priority] - PRIORITY_ORDER[b.priority],
      );
    case "priority_desc":
      return sorted.sort(
        (a, b) => PRIORITY_ORDER[b.priority] - PRIORITY_ORDER[a.priority],
      );
    case "title_asc":
      return sorted.sort((a, b) => a.title.localeCompare(b.title));
    case "title_desc":
      return sorted.sort((a, b) => b.title.localeCompare(a.title));
    case "due_date_asc":
      return sorted.sort((a, b) => {
        if (!a.due_date) return 1;
        if (!b.due_date) return -1;
        return new Date(a.due_date).getTime() - new Date(b.due_date).getTime();
      });
    case "due_date_desc":
      return sorted.sort((a, b) => {
        if (!a.due_date) return 1;
        if (!b.due_date) return -1;
        return new Date(b.due_date).getTime() - new Date(a.due_date).getTime();
      });
    case "created_at_desc":
      return sorted.sort(
        (a, b) =>
          new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      );
    case "completed":
      return sorted.sort((a, b) => Number(a.completed) - Number(b.completed));
    default:
      return sorted;
  }
}

export function groupTodosByDate(todos: Todo[]): Record<string, Todo[]> {
  const groups: Record<string, Todo[]> = {};

  for (const todo of todos) {
    const key = todo.due_date ? todo.due_date.split("T")[0] : "no_date";

    if (!groups[key]) {
      groups[key] = [];
    }
    groups[key].push(todo);
  }

  return groups;
}

export function groupTodosByProject(
  todos: Todo[],
  projects: Project[],
): Record<string, Todo[]> {
  const groups: Record<string, Todo[]> = {};
  const projectMap = new Map(projects.map((p) => [p.id, p]));

  for (const todo of todos) {
    const project = projectMap.get(todo.project_id);
    const key = project ? project.name : "No Project";

    if (!groups[key]) {
      groups[key] = [];
    }
    groups[key].push(todo);
  }

  return groups;
}

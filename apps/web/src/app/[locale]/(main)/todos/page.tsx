import { EffectTodosBranch } from "@/components/effect/EffectTodosBranch";
import TodoListPage from "@/features/todo/components/TodoListPage";
import { Priority, type TodoFilters } from "@/types/features/todoTypes";
import { EFFECT_UI_ENABLED } from "@/config/effectUi";

interface TodosPageProps {
  searchParams: Promise<{
    project?: string;
    priority?: string;
    completed?: string;
    effect?: string;
  }>;
}

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1/";

export default async function TodosPage({
  searchParams,
}: Readonly<TodosPageProps>) {
  const { project, priority, completed, effect } = await searchParams;

  if (effect === "1" && EFFECT_UI_ENABLED) {
    return <EffectTodosBranch apiBaseUrl={API_BASE_URL} />;
  }

  const filters: TodoFilters = {};

  if (project) {
    filters.project_id = project;
  }

  if (priority && Object.values(Priority).includes(priority as Priority)) {
    filters.priority = priority as Priority;
  }

  filters.completed = completed === "true";

  return <TodoListPage filters={filters} />;
}

import TodoListPage from "@/features/todo/components/TodoListPage";
import { Priority, type TodoFilters } from "@/types/features/todoTypes";

interface TodosPageProps {
  searchParams: Promise<{
    project?: string;
    priority?: string;
    completed?: string;
  }>;
}

export default async function TodosPage({
  searchParams,
}: Readonly<TodosPageProps>) {
  const { project, priority, completed } = await searchParams;

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

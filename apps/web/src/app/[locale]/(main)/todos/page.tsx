import TodoListPage from "@/features/todo/components/TodoListPage";
import { TodayView } from "@/features/todo/components/today/TodayView";
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

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      <TodayView />
      <TodoListPage filters={filters} />
    </div>
  );
}

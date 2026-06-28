import TodoListPage from "@/features/todo/components/TodoListPage";
import type { Priority } from "@/types/features/todoTypes";

interface PriorityTodosPageProps {
  params: Promise<{ priority: string }>;
}

export default async function PriorityTodosPage({
  params,
}: PriorityTodosPageProps) {
  const { priority } = await params;

  return (
    <TodoListPage
      filters={{ priority: priority as Priority, completed: false }}
    />
  );
}

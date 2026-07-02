import { notFound } from "next/navigation";
import TodoListPage from "@/features/todo/components/TodoListPage";
import { Priority } from "@/types/features/todoTypes";

interface PriorityTodosPageProps {
  params: Promise<{ priority: string }>;
}

export default async function PriorityTodosPage({
  params,
}: Readonly<PriorityTodosPageProps>) {
  const { priority } = await params;
  const parsedPriority = priority as Priority;

  if (!Object.values(Priority).includes(parsedPriority)) {
    notFound();
  }

  return (
    <TodoListPage filters={{ priority: parsedPriority, completed: false }} />
  );
}

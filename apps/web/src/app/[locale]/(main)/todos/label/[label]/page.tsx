import TodoListPage from "@/features/todo/components/TodoListPage";

interface LabelTodosPageProps {
  params: Promise<{ label: string }>;
}

export default async function LabelTodosPage({ params }: LabelTodosPageProps) {
  const { label } = await params;
  const decodedLabel = decodeURIComponent(label);

  return (
    <TodoListPage filters={{ labels: [decodedLabel], completed: false }} />
  );
}

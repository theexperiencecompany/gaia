import TodoListPage from "@/features/todo/components/TodoListPage";

interface ProjectTodosPageProps {
  params: Promise<{ projectId: string }>;
}

export default async function ProjectTodosPage({
  params,
}: Readonly<ProjectTodosPageProps>) {
  const { projectId } = await params;

  return <TodoListPage filters={{ project_id: projectId, completed: false }} />;
}

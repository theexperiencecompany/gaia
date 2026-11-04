import "./page.css";
import "./page.2.css";
import "./page.3.css";
import "./page.4.css";
import "./page.5.css";
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

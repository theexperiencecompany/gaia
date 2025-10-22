"use client";

import { useParams } from "next/navigation";

import TodoListPage from "@/features/todo/components/TodoListPage";

export default function ProjectTodosPage() {
  const params = useParams();
  const projectId = params.projectId as string;

  // Get projects to find the project name
  // const { projects } = useTodoData({ autoLoad: false });

  // const project = useMemo(() => {
  //   return projects.find((p) => p.id === projectId);
  // }, [projects, projectId]);

  return (
    <TodoListPage filters={{ project_id: projectId }} showCompleted={false} />
  );
}

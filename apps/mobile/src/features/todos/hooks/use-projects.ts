import { useCallback, useEffect } from "react";
import { useShallow } from "zustand/react/shallow";
import { useTodoStore } from "../store/todo-store";
import type { Project } from "../types/todo-types";

interface ProjectCreate {
  name: string;
  color?: string;
  description?: string;
}

interface ProjectUpdate {
  name?: string;
  color?: string;
  description?: string;
}

/**
 * React hook over the shared todo store, scoped to projects.
 *
 * Loads projects on mount and exposes CRUD + a `getTodoCount` helper that
 * reads from the project's denormalized `todo_count` field.
 */
export function useProjects() {
  const {
    projects,
    initialLoading,
    error,
    loadProjects,
    createProject,
    updateProject,
    deleteProject,
  } = useTodoStore(
    useShallow((state) => ({
      projects: state.projects,
      initialLoading: state.initialLoading,
      error: state.error,
      loadProjects: state.loadProjects,
      createProject: state.createProject,
      updateProject: state.updateProject,
      deleteProject: state.deleteProject,
    })),
  );

  useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

  const refetch = useCallback(async () => {
    await loadProjects();
  }, [loadProjects]);

  const getTodoCount = useCallback(
    (projectId: string): number => {
      const project = projects.find((p: Project) => p.id === projectId);
      return project?.todo_count ?? 0;
    },
    [projects],
  );

  return {
    projects,
    isLoading: initialLoading,
    isRefreshing: false,
    error,
    refetch,
    createProject: (data: ProjectCreate) => createProject(data),
    updateProject: (id: string, data: ProjectUpdate) => updateProject(id, data),
    deleteProject,
    getTodoCount,
  };
}

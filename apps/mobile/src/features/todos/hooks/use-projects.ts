import { useCallback, useEffect, useState } from "react";
import { todoApi } from "../api/todo-api";
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

interface UseProjectsState {
  projects: Project[];
  isLoading: boolean;
  isRefreshing: boolean;
  error: string | null;
}

interface UseProjectsReturn extends UseProjectsState {
  refetch: () => Promise<void>;
  createProject: (data: ProjectCreate) => Promise<Project>;
  updateProject: (id: string, data: ProjectUpdate) => Promise<Project>;
  deleteProject: (id: string) => Promise<void>;
  getTodoCount: (projectId: string) => number;
}

export function useProjects(): UseProjectsReturn {
  const [state, setState] = useState<UseProjectsState>({
    projects: [],
    isLoading: true,
    isRefreshing: false,
    error: null,
  });

  const fetchProjects = useCallback(async (isRefresh = false) => {
    setState((prev) => ({
      ...prev,
      isLoading: !isRefresh,
      isRefreshing: isRefresh,
      error: null,
    }));

    try {
      const projects = await todoApi.getAllProjects();
      setState((prev) => ({
        ...prev,
        projects,
        isLoading: false,
        isRefreshing: false,
      }));
    } catch (err) {
      setState((prev) => ({
        ...prev,
        isLoading: false,
        isRefreshing: false,
        error: err instanceof Error ? err.message : "Failed to load projects",
      }));
    }
  }, []);

  useEffect(() => {
    void fetchProjects();
  }, [fetchProjects]);

  const refetch = useCallback(async () => {
    await fetchProjects(true);
  }, [fetchProjects]);

  const createProject = useCallback(
    async (data: ProjectCreate): Promise<Project> => {
      const project = await todoApi.createProject(data);
      setState((prev) => ({
        ...prev,
        projects: [...prev.projects, project],
      }));
      return project;
    },
    [],
  );

  const updateProject = useCallback(
    async (id: string, data: ProjectUpdate): Promise<Project> => {
      const updated = await todoApi.updateProject(id, data);
      setState((prev) => ({
        ...prev,
        projects: prev.projects.map((p) => (p.id === id ? updated : p)),
      }));
      return updated;
    },
    [],
  );

  const deleteProject = useCallback(async (id: string): Promise<void> => {
    await todoApi.deleteProject(id);
    setState((prev) => ({
      ...prev,
      projects: prev.projects.filter((p) => p.id !== id),
    }));
  }, []);

  const getTodoCount = useCallback(
    (projectId: string): number => {
      const project = state.projects.find((p) => p.id === projectId);
      return project?.todo_count ?? 0;
    },
    [state.projects],
  );

  return {
    ...state,
    refetch,
    createProject,
    updateProject,
    deleteProject,
    getTodoCount,
  };
}

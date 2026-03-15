"use client";

import { useSearchParams } from "next/navigation";
import { useMemo } from "react";

import TodoListPage from "@/features/todo/components/TodoListPage";
import { Priority, type TodoFilters } from "@/types/features/todoTypes";

export default function TodosPage() {
  const searchParams = useSearchParams();

  const projectId = searchParams.get("project");
  const priority = searchParams.get("priority");
  const completedParam = searchParams.get("completed");

  const filters = useMemo((): TodoFilters => {
    const urlFilters: TodoFilters = {};

    if (projectId) {
      urlFilters.project_id = projectId;
    }

    if (priority) {
      const priorityValue = Object.values(Priority).includes(
        priority as Priority,
      )
        ? (priority as Priority)
        : undefined;
      if (priorityValue) urlFilters.priority = priorityValue;
    }

    urlFilters.completed = completedParam === "true";

    return urlFilters;
  }, [projectId, priority, completedParam]);

  return <TodoListPage filters={filters} />;
}

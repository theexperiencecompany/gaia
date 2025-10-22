"use client";

import { useParams } from "next/navigation";
import { useMemo } from "react";

import TodoListPage from "@/features/todo/components/TodoListPage";
import { Priority } from "@/types/features/todoTypes";

export default function PriorityTodosPage() {
  const params = useParams();
  const priority = params.priority as Priority;
  const filters = useMemo(() => ({ priority, completed: false }), [priority]);
  return <TodoListPage filters={filters} />;
}

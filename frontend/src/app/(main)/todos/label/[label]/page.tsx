"use client";

import { useParams } from "next/navigation";

import TodoListPage from "@/features/todo/components/TodoListPage";
import { Todo } from "@/types/features/todoTypes";

export default function LabelTodosPage() {
  const params = useParams();
  const label = decodeURIComponent(params.label as string);

  return <TodoListPage filters={{ labels: [label], completed: false }} />;
}

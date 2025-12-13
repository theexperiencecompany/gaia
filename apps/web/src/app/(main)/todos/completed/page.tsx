"use client";

import TodoListPage from "@/features/todo/components/TodoListPage";

export default function CompletedTodosPage() {
  return <TodoListPage filters={{ completed: true }} />;
}

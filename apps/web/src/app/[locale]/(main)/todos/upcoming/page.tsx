"use client";

import TodoListPage from "@/features/todo/components/TodoListPage";

export default function UpcomingTodosPage() {
  return <TodoListPage filters={{ due_this_week: true, completed: false }} />;
}

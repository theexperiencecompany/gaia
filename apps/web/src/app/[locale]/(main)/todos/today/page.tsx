"use client";

import TodoListPage from "@/features/todo/components/TodoListPage";

export default function TodayTodosPage() {
  return <TodoListPage filters={{ due_today: true, completed: false }} />;
}

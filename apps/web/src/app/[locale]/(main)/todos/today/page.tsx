"use client";

import TodoListPage from "@/features/todo/components/TodoListPage";
import type { Todo } from "@/types/features/todoTypes";

const filterTodayTodos = (todos: Todo[]) => {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const tomorrow = new Date(today);
  tomorrow.setDate(tomorrow.getDate() + 1);

  return todos.filter((todo) => {
    if (!todo.due_date) return false;
    const dueDate = new Date(todo.due_date);
    return dueDate >= today && dueDate < tomorrow;
  });
};

export default function TodayTodosPage() {
  return (
    <TodoListPage
      filters={{ due_today: true, completed: false }}
      filterTodos={filterTodayTodos}
    />
  );
}

"use client";

import TodoListPage from "@/features/todo/components/TodoListPage";
import { Todo } from "@/types/features/todoTypes";

export default function TodayTodosPage() {
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

  return (
    <TodoListPage
      filters={{ due_today: true, completed: false }}
      filterTodos={filterTodayTodos}
    />
  );
}

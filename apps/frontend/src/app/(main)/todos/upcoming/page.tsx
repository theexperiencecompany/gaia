"use client";

import TodoListPage from "@/features/todo/components/TodoListPage";
import type { Todo } from "@/types/features/todoTypes";

export default function UpcomingTodosPage() {
  const filterUpcomingTodos = (todos: Todo[]) => {
    const today = new Date();
    const nextWeek = new Date(today);
    nextWeek.setDate(nextWeek.getDate() + 7);

    return todos.filter((todo) => {
      if (!todo.due_date) return false;
      const dueDate = new Date(todo.due_date);
      return dueDate >= today && dueDate <= nextWeek;
    });
  };

  return (
    <TodoListPage
      filters={{ due_this_week: true, completed: false }}
      filterTodos={filterUpcomingTodos}
    />
  );
}

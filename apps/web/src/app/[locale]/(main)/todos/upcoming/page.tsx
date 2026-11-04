"use client";

import TodoListPage from "@/features/todo/components/TodoListPage";
import type { Todo } from "@/types/features/todoTypes";

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

export default function UpcomingTodosPage() {
  return (
    <TodoListPage
      filters={{ due_this_week: true, completed: false }}
      filterTodos={filterUpcomingTodos}
    />
  );
}

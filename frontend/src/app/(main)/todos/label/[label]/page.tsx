"use client";

import { useParams } from "next/navigation";

import TodoListPage from "@/features/todo/components/TodoListPage";
import { Todo } from "@/types/features/todoTypes";

export default function LabelTodosPage() {
  const params = useParams();
  const label = decodeURIComponent(params.label as string);

  // Filter function to show only todos with the specific label
  const filterTodosByLabel = (todos: Todo[]) => {
    return todos.filter((todo) => todo.labels && todo.labels.includes(label));
  };

  return (
    <TodoListPage filterTodos={filterTodosByLabel} showCompleted={false} />
  );
}

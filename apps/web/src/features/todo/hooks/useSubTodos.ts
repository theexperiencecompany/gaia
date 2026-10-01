import { useQuery } from "@tanstack/react-query";

import { todoApi } from "@/features/todo/api/todoApi";
import { SUB_TODOS_PAGE_SIZE } from "@/features/todo/constants";
import type { Todo } from "@/types/features/todoTypes";

/** A tracked todo's sub-todos, open and completed; refetched when its open count moves. */
export const useSubTodos = (parentTodoId: string, openCount: number) =>
  useQuery({
    queryKey: ["todos", "sub-todos", parentTodoId, openCount],
    queryFn: async (): Promise<Todo[]> =>
      await todoApi.getAllTodos({
        parent_todo_id: parentTodoId,
        limit: SUB_TODOS_PAGE_SIZE,
      }),
  });

import { useInfiniteQuery } from "@tanstack/react-query";

import { todoApi } from "@/features/todo/api/todoApi";
import { SUB_TODOS_PAGE_SIZE } from "@/features/todo/constants";
import type { Todo } from "@/types/features/todoTypes";

/** A tracked todo's sub-todos, open and completed, a page at a time; refetched when its open count moves. */
export const useSubTodos = (parentTodoId: string, openCount: number) =>
  useInfiniteQuery({
    queryKey: ["todos", "sub-todos", parentTodoId, openCount],
    queryFn: async ({ pageParam }): Promise<Todo[]> =>
      await todoApi.getAllTodos({
        parent_todo_id: parentTodoId,
        skip: pageParam,
        limit: SUB_TODOS_PAGE_SIZE,
      }),
    initialPageParam: 0,
    getNextPageParam: (lastPage, pages) =>
      lastPage.length === SUB_TODOS_PAGE_SIZE
        ? pages.length * SUB_TODOS_PAGE_SIZE
        : undefined,
  });

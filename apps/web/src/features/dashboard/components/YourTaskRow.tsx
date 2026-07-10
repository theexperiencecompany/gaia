"use client";

import { Button } from "@heroui/button";
import { Checkbox } from "@heroui/checkbox";
import { SparklesIcon } from "@icons";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import type React from "react";
import { useHandoffTodo } from "@/features/todo/hooks/useHandoffTodo";
import { useTodoStore } from "@/stores/todoStore";
import type { TodayYourTaskItem } from "@/types/features/dashboardTypes";

import { TODAY_QUERY_KEY } from "../hooks/useTodayQuery";

interface YourTaskRowProps {
  item: TodayYourTaskItem;
}

/** One of the user's own todos due today; the offer tag hands it to GAIA. */
export const YourTaskRow: React.FC<YourTaskRowProps> = ({ item }) => {
  const router = useRouter();
  const queryClient = useQueryClient();
  const handoffTodo = useHandoffTodo();

  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: TODAY_QUERY_KEY });

  const complete = async (checked: boolean) => {
    if (!checked) return;
    await useTodoStore.getState().updateTodo(item.todo_id, { completed: true });
    refresh();
  };

  return (
    // Row click opens the todo in the sidebar; checkbox and CTA stay local.
    <div
      className="group flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2 transition-colors hover:bg-zinc-900"
      onClick={() => router.push(`/todos?todoId=${item.todo_id}`)}
    >
      <div onClick={(e) => e.stopPropagation()}>
        <Checkbox
          size="sm"
          radius="full"
          aria-label={`Mark "${item.title}" done`}
          onValueChange={complete}
          classNames={{ wrapper: "mr-0" }}
        />
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-zinc-200">
          {item.title}
        </p>
        {item.serves && (
          <p className="truncate text-xs text-zinc-500">{item.serves}</p>
        )}
      </div>
      {item.gaia_offer && (
        <div onClick={(e) => e.stopPropagation()}>
          <Button
            size="sm"
            variant="light"
            radius="lg"
            className="shrink-0 text-violet-400"
            startContent={<SparklesIcon className="size-3.5" />}
            isLoading={handoffTodo.isPending}
            onPress={() =>
              handoffTodo.mutate(item.todo_id, { onSuccess: refresh })
            }
          >
            Let GAIA handle it
          </Button>
        </div>
      )}
    </div>
  );
};

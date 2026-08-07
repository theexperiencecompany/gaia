"use client";

import { Button } from "@heroui/button";
import { PlayIcon } from "@icons";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import type React from "react";
import { StatusGlyph } from "@/components/shared/StatusGlyph";
import { useHandoffTodo } from "@/features/todo/hooks/useHandoffTodo";
import type { TodaySuggestedItem } from "@/types/features/todayTypes";
import { TODAY_QUERY_KEY } from "../../hooks/useTodayQuery";

interface SuggestedRowProps {
  item: TodaySuggestedItem;
}

/** A user todo GAIA has offered to take over — Run hands it off (`gaia_offer`). */
export const SuggestedRow: React.FC<SuggestedRowProps> = ({ item }) => {
  const router = useRouter();
  const queryClient = useQueryClient();
  const handoffTodo = useHandoffTodo();

  return (
    // Row click opens the todo (offer details + handoff) in the sidebar.
    <div
      className="group flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2 transition-colors hover:bg-zinc-900"
      onClick={() => router.push(`/todos?todoId=${item.todo_id}`)}
    >
      <StatusGlyph kind="suggested" className="shrink-0" />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-zinc-200">
          {item.title}
        </p>
        <p className="truncate text-xs text-zinc-500">{item.gaia_offer}</p>
      </div>
      <div onClick={(e) => e.stopPropagation()}>
        <Button
          size="sm"
          color="success"
          variant="flat"
          radius="lg"
          className="shrink-0"
          startContent={<PlayIcon className="size-3.5" />}
          isLoading={handoffTodo.isPending}
          onPress={() =>
            handoffTodo.mutate(item.todo_id, {
              onSuccess: () =>
                queryClient.invalidateQueries({ queryKey: TODAY_QUERY_KEY }),
            })
          }
        >
          Run
        </Button>
      </div>
    </div>
  );
};

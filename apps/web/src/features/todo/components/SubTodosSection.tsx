"use client";

import { Chip, Spinner } from "@heroui/react";
import { Clock01Icon, Tag01Icon } from "@icons";
import { formatDistanceToNow } from "date-fns";
import Link from "next/link";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { shapeVariants } from "@/components/shared/shape";
import { useSubTodos } from "@/features/todo/hooks/useSubTodos";

interface SubTodosSectionProps {
  parentTodoId: string;
  openCount: number;
}

export function SubTodosSection({
  parentTodoId,
  openCount,
}: SubTodosSectionProps) {
  const {
    data,
    isLoading,
    isError,
    hasNextPage,
    fetchNextPage,
    isFetchingNextPage,
  } = useSubTodos(parentTodoId, openCount);
  const subTodos = data?.pages.flat();

  // Finished sub-todos still show; a todo that never had any shows nothing.
  if (subTodos?.length === 0 || (openCount === 0 && isLoading)) return null;

  return (
    <section className="space-y-2" aria-label="Sub-todos">
      <p className="text-xs font-medium text-zinc-400">
        Sub-todos ({openCount} open)
      </p>
      {isLoading && <Spinner size="sm" />}
      {isError && (
        <p className="text-xs text-zinc-500">Couldn't load the sub-todos.</p>
      )}
      <ul className="flex flex-col gap-2">
        {subTodos?.map((subTodo) => (
          <li key={subTodo.id} className="rounded-2xl bg-zinc-800 px-3 py-2">
            <Link
              href={`/todos?todoId=${subTodo.id}`}
              className="text-sm text-zinc-200 hover:underline"
            >
              {subTodo.title}
            </Link>
            <div className="mt-1 flex flex-wrap items-center gap-1">
              {subTodo.completed && (
                <Chip
                  className={shapeVariants({ shape: "sm" })}
                  size="sm"
                  variant="soft"
                  color="success"
                >
                  Completed
                </Chip>
              )}
              {subTodo.labels.map((label) => (
                <Chip
                  className={shapeVariants({ shape: "sm" })}
                  key={label}
                  size="sm"
                  variant="soft"
                >
                  <Tag01Icon width={14} height={14} className="mx-1" />
                  <Chip.Label>{label}</Chip.Label>
                </Chip>
              ))}
              {subTodo.scheduled_at && (
                <Chip
                  className={shapeVariants({ shape: "sm" })}
                  size="sm"
                  variant="soft"
                  color="accent"
                >
                  <Clock01Icon width={14} height={14} className="mx-1" />
                  <Chip.Label>
                    {formatDistanceToNow(new Date(subTodo.scheduled_at), {
                      addSuffix: true,
                    })}
                  </Chip.Label>
                </Chip>
              )}
            </div>
            <p className="mt-1 font-mono text-xs text-zinc-500">{subTodo.id}</p>
          </li>
        ))}
      </ul>
      {hasNextPage && (
        <GaiaButton
          size="sm"
          variant="default-soft"
          isPending={isFetchingNextPage}
          onPress={() => fetchNextPage()}
        >
          Load more
        </GaiaButton>
      )}
    </section>
  );
}

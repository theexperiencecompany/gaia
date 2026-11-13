import { Button } from "@heroui/button";
import { Skeleton } from "@heroui/skeleton";
import { NotificationIcon } from "@icons";
import type { UpdateFilter } from "@shared/api/generated";
import { useUpdates } from "../hooks/useUpdates";
import { UpdateRowCard } from "./UpdateRowCard";

const EMPTY_TITLES: Record<UpdateFilter, string> = {
  all: "Nothing yet",
  needs_you: "Nothing needs you",
  done: "Nothing done yet",
  failed: "Nothing failed",
  held: "Nothing is waiting",
};

interface UpdatesFeedProps {
  filter: UpdateFilter;
}

export function UpdatesFeed({ filter }: UpdatesFeedProps) {
  const {
    updates,
    isLoading,
    isError,
    hasMore,
    isLoadingMore,
    loadMore,
    refetch,
  } = useUpdates(filter);

  if (isLoading) {
    return (
      <div className="space-y-2">
        {[0, 1, 2].map((key) => (
          <Skeleton key={key} className="h-24 w-full rounded-2xl" />
        ))}
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex flex-col items-center gap-3 p-8 text-center">
        <p className="font-medium text-zinc-300">Could not load updates</p>
        <Button size="sm" variant="flat" onPress={() => refetch()}>
          Try again
        </Button>
      </div>
    );
  }

  if (updates.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center p-8 text-center">
        <NotificationIcon className="mb-4 size-10 text-zinc-600" />
        <p className="font-medium text-zinc-300">{EMPTY_TITLES[filter]}</p>
        <p className="mt-1 text-sm text-zinc-400">
          What GAIA tells you, and what it only keeps a record of, shows up
          here.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {updates.map((row) => (
        <UpdateRowCard key={row.report_id} row={row} />
      ))}
      {hasMore && (
        <Button
          fullWidth
          variant="flat"
          isLoading={isLoadingMore}
          onPress={() => loadMore()}
        >
          Load more
        </Button>
      )}
    </div>
  );
}

import type { UpdateFilter, UpdateRow } from "@shared/api/generated";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { updatesKeys } from "../api/queryKeys";
import { updatesApi } from "../api/updatesApi";

export function useUpdates(filter: UpdateFilter) {
  const query = useInfiniteQuery({
    queryKey: updatesKeys.feed(filter),
    queryFn: ({ pageParam }) => updatesApi.list(filter, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_before,
  });

  const updates = useMemo<UpdateRow[]>(
    () => query.data?.pages.flatMap((page) => page.updates) ?? [],
    [query.data],
  );

  return {
    updates,
    isLoading: query.isLoading,
    isError: query.isError,
    hasMore: query.hasNextPage,
    isLoadingMore: query.isFetchingNextPage,
    loadMore: query.fetchNextPage,
    refetch: query.refetch,
  };
}

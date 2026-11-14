import { useInfiniteQuery } from "@tanstack/react-query";

import { briefingApi } from "../api/briefingApi";

/** The user's past briefings (archive), most recent first, a page at a time. */
export const useBriefingsQuery = () =>
  useInfiniteQuery({
    queryKey: ["briefings", "archive"],
    queryFn: ({ pageParam }) => briefingApi.fetchBriefings(pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 30 * 60 * 1000, // 30 minutes - cache persistence
    retry: 2,
    refetchOnWindowFocus: false,
  });

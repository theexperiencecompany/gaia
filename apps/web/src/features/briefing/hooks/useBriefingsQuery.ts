import { useInfiniteQuery } from "@tanstack/react-query";

import { briefingApi } from "../api/briefingApi";
import { BRIEFING_STALE_MS, briefingKeys } from "../api/queryKeys";

/** How long the archive's pages are kept after the page is left. */
const ARCHIVE_GC_MS = 30 * 60 * 1000;

/** The user's past briefings (archive), most recent first, a page at a time. */
export const useBriefingsQuery = () =>
  useInfiniteQuery({
    queryKey: briefingKeys.archive,
    queryFn: ({ pageParam }) => briefingApi.fetchBriefings(pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    staleTime: BRIEFING_STALE_MS,
    gcTime: ARCHIVE_GC_MS,
    retry: 2,
  });

import { useQuery } from "@tanstack/react-query";

import { briefingApi } from "../api/briefingApi";

/** One brief by id, for its standalone page. */
export const useBriefingQuery = (briefingId: string) =>
  useQuery({
    queryKey: ["briefing", briefingId],
    queryFn: () => briefingApi.fetchBriefing(briefingId),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

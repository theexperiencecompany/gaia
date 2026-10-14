import type { PostmarksResponse } from "@shared/api/generated";
import { useQuery } from "@tanstack/react-query";

import { briefingApi } from "../api/briefingApi";

/** The user's collected Air Mail city stamps and how many exist. */
export const usePostmarksQuery = () =>
  useQuery<PostmarksResponse>({
    queryKey: ["briefings", "postmarks"],
    queryFn: briefingApi.fetchPostmarks,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

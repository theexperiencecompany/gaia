import {
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import {
  addPublicIntegration,
  getCommunityIntegrations,
} from "../api/integrations-api";
import type { CommunityIntegration, CommunitySearchParams } from "../types";

const PAGE_SIZE = 20;

export const communityIntegrationsKeys = {
  all: ["communityIntegrations"] as const,
  list: (params: Omit<CommunitySearchParams, "offset" | "limit">) =>
    [...communityIntegrationsKeys.all, "list", params] as const,
};

interface UseCommunityIntegrationsParams {
  search?: string;
  category?: string;
  sort?: "popular" | "recent" | "name";
}

interface CommunityIntegrationsPage {
  integrations: CommunityIntegration[];
  total: number;
  hasMore: boolean;
  nextOffset: number;
}

export function useCommunityIntegrations(
  params: UseCommunityIntegrationsParams = {},
) {
  const { search, category, sort = "popular" } = params;

  const query = useInfiniteQuery({
    queryKey: communityIntegrationsKeys.list({ search, category, sort }),
    queryFn: async ({ pageParam }) => {
      const offset = pageParam as number;
      const response = await getCommunityIntegrations({
        search,
        category,
        sort,
        limit: PAGE_SIZE,
        offset,
      });
      return {
        integrations: response.integrations,
        total: response.total,
        hasMore: response.hasMore,
        nextOffset: offset + PAGE_SIZE,
      } satisfies CommunityIntegrationsPage;
    },
    initialPageParam: 0,
    getNextPageParam: (lastPage: CommunityIntegrationsPage) =>
      lastPage.hasMore ? lastPage.nextOffset : undefined,
    staleTime: 2 * 60 * 1000,
  });

  const integrations = query.data?.pages.flatMap((p) => p.integrations) ?? [];
  const total = query.data?.pages[0]?.total ?? 0;

  return {
    integrations,
    total,
    isLoading: query.isLoading,
    isFetchingNextPage: query.isFetchingNextPage,
    hasNextPage: query.hasNextPage,
    fetchNextPage: query.fetchNextPage,
    error: query.error,
    refetch: query.refetch,
  };
}

export function useAddPublicIntegration() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      slug,
      bearerToken,
    }: {
      slug: string;
      bearerToken?: string;
    }) => addPublicIntegration(slug, bearerToken),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: communityIntegrationsKeys.all,
      });
    },
  });
}

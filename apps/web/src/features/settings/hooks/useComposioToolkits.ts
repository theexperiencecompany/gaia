"use client";

import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { integrationKeys } from "@/features/integrations/api/queryKeys";
import {
  COMPOSIO_CATALOG_PAGE_SIZE,
  composioSetupApi,
} from "@/features/settings/api/composioSetupApi";
import { setupKeys } from "@/features/settings/api/queryKeys";
import { toast } from "@/lib/toast";

/** One searched, paged view of Composio's toolkit catalog. */
export function useComposioCatalog(query: string, category: string | null) {
  return useInfiniteQuery({
    queryKey: setupKeys.composioToolkitList(query, category),
    queryFn: ({ pageParam }) =>
      composioSetupApi.searchToolkits(query, category, pageParam),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.length * COMPOSIO_CATALOG_PAGE_SIZE;
      return loaded < last.total ? loaded : undefined;
    },
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}

/** How enabling one toolkit authenticates and which values it needs. */
export function useComposioToolkit(slug: string | null) {
  return useQuery({
    queryKey: setupKeys.composioToolkit(slug),
    queryFn: () => composioSetupApi.fetchToolkit(slug ?? ""),
    enabled: slug !== null,
    staleTime: 60_000,
  });
}

/** Enable and disable toolkits, refreshing the catalog, the setup list and the integrations page. */
export function useComposioToolkitActions() {
  const queryClient = useQueryClient();
  const refresh = () => {
    // The composio prefix covers the setup list and the toolkit catalog under it.
    void queryClient.invalidateQueries({ queryKey: setupKeys.composio });
    void queryClient.invalidateQueries({ queryKey: integrationKeys.all });
  };

  const enable = useMutation({
    mutationFn: ({
      slug,
      credentials,
    }: {
      slug: string;
      name: string;
      credentials: Record<string, string>;
    }) => composioSetupApi.enableToolkit(slug, credentials),
    onSuccess: (_data, { name }) => {
      refresh();
      toast.success(`${name} is ready to connect`);
    },
  });

  const disable = useMutation({
    mutationFn: ({ slug }: { slug: string; name: string }) =>
      composioSetupApi.disableToolkit(slug),
    onSuccess: (_data, { name }) => {
      refresh();
      toast.success(`${name} removed`);
    },
  });

  return { enable, disable };
}

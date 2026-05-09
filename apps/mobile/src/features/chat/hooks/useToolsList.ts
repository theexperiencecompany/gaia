import { useQuery } from "@tanstack/react-query";
import { apiService } from "@/lib/api";

export interface ToolInfo {
  name: string;
  category: string;
  display_name: string;
  icon_url?: string;
  requires_integration: boolean;
}

export interface ToolsListResponse {
  tools: ToolInfo[];
  total_count: number;
  categories: string[];
}

const TOOLS_LIST_QUERY_KEY = ["tools", "list"] as const;
const TOOLS_LIST_STALE_TIME_MS = 60 * 1000;

interface UseToolsListResult {
  tools: ToolInfo[];
  categories: string[];
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  refetch: () => void;
}

/**
 * Slash-command sheet uses a different shape from the global Tools page —
 * `display_name`, `icon_url`, and `requires_integration` per tool — so this
 * hook owns its own query key and types.
 */
export function useToolsList(enabled: boolean): UseToolsListResult {
  const query = useQuery({
    queryKey: TOOLS_LIST_QUERY_KEY,
    queryFn: () => apiService.get<ToolsListResponse>("/tools"),
    enabled,
    staleTime: TOOLS_LIST_STALE_TIME_MS,
  });

  return {
    tools: query.data?.tools ?? [],
    categories: query.data?.categories ?? [],
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    refetch: () => {
      void query.refetch();
    },
  };
}

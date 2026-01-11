import { useQuery } from "@tanstack/react-query";

import { fetchAvailableTools, type ToolInfo } from "../api/toolsApi";

export interface UseToolsQueryReturn {
  tools: ToolInfo[];
  isLoading: boolean;
  error: string | null;
  refetch: () => void;
}

/**
 * React Query hook for fetching available tools with caching
 * Reduced staleTime to allow faster updates after MCP connections
 */
export const useToolsQuery = (): UseToolsQueryReturn => {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["tools", "available"],
    queryFn: fetchAvailableTools,
    staleTime: 5 * 60 * 1000, // 5 minutes - reduced to allow faster updates after MCP connection
    gcTime: 30 * 60 * 1000, // 30 minutes - keep in cache
    retry: 2,
    refetchOnWindowFocus: false, // Don't refetch when user focuses window
  });

  return {
    tools: data?.tools || [],
    isLoading,
    error: error
      ? error instanceof Error
        ? error.message
        : "Failed to load tools"
      : null,
    refetch,
  };
};

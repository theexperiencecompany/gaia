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
 * Caches the response for 3 hours to improve performance
 */
export const useToolsQuery = (): UseToolsQueryReturn => {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["tools", "available"],
    queryFn: fetchAvailableTools,
    staleTime: 3 * 60 * 60 * 1000, // 3 hours - cache for a few hours as requested
    gcTime: 6 * 60 * 60 * 1000, // 6 hours - keep in cache longer than staleTime
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

import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { useCallback } from "react";
import {
  mcpApi,
  MCPServerTemplate,
  MCPServer,
  MCPServerCreateRequest,
} from "../api/mcpApi";

export interface UseMCPServersReturn {
  templates: MCPServerTemplate[];
  servers: MCPServer[];
  isLoading: boolean;
  error: Error | null;
  createServer: (request: MCPServerCreateRequest) => Promise<MCPServer>;
  deleteServer: (serverId: number) => Promise<void>;
  refreshServers: () => void;
}

export const useMCPServers = (): UseMCPServersReturn => {
  const queryClient = useQueryClient();

  // Query for MCP templates
  const { data: templatesData, isLoading: templatesLoading } = useQuery({
    queryKey: ["mcp", "templates"],
    queryFn: mcpApi.getMCPTemplates,
    staleTime: 60 * 60 * 1000, // 1 hour
    gcTime: 2 * 60 * 60 * 1000, // 2 hours
  });

  // Query for user's configured MCP servers
  const {
    data: serversData,
    isLoading: serversLoading,
    error,
  } = useQuery({
    queryKey: ["mcp", "servers"],
    queryFn: mcpApi.listMCPServers,
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 10 * 60 * 1000, // 10 minutes
  });

  // Create server mutation
  const createMutation = useMutation({
    mutationFn: mcpApi.createMCPServer,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["mcp", "servers"] });
    },
  });

  // Delete server mutation
  const deleteMutation = useMutation({
    mutationFn: mcpApi.deleteMCPServer,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["mcp", "servers"] });
    },
  });

  const createServer = useCallback(
    async (request: MCPServerCreateRequest): Promise<MCPServer> => {
      return createMutation.mutateAsync(request);
    },
    [createMutation],
  );

  const deleteServer = useCallback(
    async (serverId: number): Promise<void> => {
      return deleteMutation.mutateAsync(serverId);
    },
    [deleteMutation],
  );

  const refreshServers = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["mcp", "servers"] });
  }, [queryClient]);

  return {
    templates: templatesData || [],
    servers: serversData || [],
    isLoading: templatesLoading || serversLoading,
    error: error as Error | null,
    createServer,
    deleteServer,
    refreshServers,
  };
};

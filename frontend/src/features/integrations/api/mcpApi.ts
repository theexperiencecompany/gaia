import { apiService } from "@/lib/api";

export interface MCPServerTemplate {
  id: string;
  name: string;
  description: string;
  category: string;
  server_url?: string;
  setup_instructions: string;
  requires_auth: boolean;
  auth_type?: string;
  documentation_url: string;
  icon_url: string;
}

export interface MCPServer {
  id: number;
  name: string;
  description: string;
  server_type: "stdio" | "http" | "sse";
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface MCPServerCreateRequest {
  name: string;
  description: string;
  server_type: "stdio" | "http" | "sse";
  enabled?: boolean;
  http_config?: {
    url: string;
    headers?: Record<string, string>;
    timeout?: number;
  };
  auth_config?: {
    auth_type: "none" | "bearer" | "oauth2" | "basic" | "custom";
    bearer_token?: string;
    oauth_client_id?: string;
    oauth_client_secret?: string;
    basic_username?: string;
    basic_password?: string;
    custom_headers?: Record<string, string>;
  };
}

export interface MCPServerStatus {
  server_id: number;
  name: string;
  connected: boolean;
  tool_count: number;
  tools: Array<{
    name: string;
    description: string;
    server_name: string;
  }>;
  error?: string;
}

export const mcpApi = {
  /**
   * Get MCP server registry/templates
   */
  getMCPTemplates: async (): Promise<MCPServerTemplate[]> => {
    try {
      // This endpoint should return templates from mcp_registry.py
      const response = await apiService.get("/mcp/templates");
      return response as MCPServerTemplate[];
    } catch (error) {
      console.error("Failed to get MCP templates:", error);
      // Return empty array as fallback
      return [];
    }
  },

  /**
   * List user's configured MCP servers
   */
  listMCPServers: async (): Promise<MCPServer[]> => {
    try {
      const response = await apiService.get("/mcp/servers");
      return (response as { servers: MCPServer[] }).servers;
    } catch (error) {
      console.error("Failed to list MCP servers:", error);
      return [];
    }
  },

  /**
   * Create a new MCP server
   */
  createMCPServer: async (
    request: MCPServerCreateRequest,
  ): Promise<MCPServer> => {
    try {
      const response = await apiService.post("/mcp/servers", request);
      return response as MCPServer;
    } catch (error) {
      console.error("Failed to create MCP server:", error);
      throw error;
    }
  },

  /**
   * Get MCP server details
   */
  getMCPServer: async (serverId: number): Promise<MCPServer> => {
    try {
      const response = await apiService.get(`/mcp/servers/${serverId}`);
      return response as MCPServer;
    } catch (error) {
      console.error(`Failed to get MCP server ${serverId}:`, error);
      throw error;
    }
  },

  /**
   * Update MCP server
   */
  updateMCPServer: async (
    serverId: number,
    updates: Partial<MCPServerCreateRequest>,
  ): Promise<MCPServer> => {
    try {
      const response = await apiService.put(
        `/mcp/servers/${serverId}`,
        updates,
      );
      return response as MCPServer;
    } catch (error) {
      console.error(`Failed to update MCP server ${serverId}:`, error);
      throw error;
    }
  },

  /**
   * Delete MCP server
   */
  deleteMCPServer: async (serverId: number): Promise<void> => {
    try {
      await apiService.delete(`/mcp/servers/${serverId}`);
    } catch (error) {
      console.error(`Failed to delete MCP server ${serverId}:`, error);
      throw error;
    }
  },

  /**
   * Get MCP server connection status
   */
  getMCPServerStatus: async (serverId: number): Promise<MCPServerStatus> => {
    try {
      const response = await apiService.get(`/mcp/servers/${serverId}/status`);
      return response as MCPServerStatus;
    } catch (error) {
      console.error(`Failed to get MCP server status ${serverId}:`, error);
      throw error;
    }
  },
};

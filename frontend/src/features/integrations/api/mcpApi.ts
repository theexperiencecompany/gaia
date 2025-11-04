import { apiService } from "@/lib/api";

export interface MCPServerTemplate {
  id: string;
  name: string;
  description: string;
  category: string;
  server_url?: string;
  setup_instructions: string;
  requires_auth: boolean;
  auth_type?: "oauth" | "bearer" | "api_key"; // Authentication type
  oauth_integration_id?: string; // If set, use OAuth instead of manual token
  documentation_url: string;
  icon_url: string;
}

export interface MCPServer {
  _id: string;
  user_id: string;
  server_name: string;
  display_name: string;
  description: string;
  mcp_config: Record<string, any>;
  oauth_integration_id?: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface MCPServerStatusSummary {
  template_id: string;
  name: string;
  icon_url: string;
  category: string;
  requires_auth: boolean;
  auth_type?: "oauth" | "bearer" | "api_key";
  oauth_integration_id?: string;
  is_configured: boolean;
  is_enabled: boolean;
  is_oauth_connected: boolean;
  connected: boolean;
}

export interface MCPServerCreateRequest {
  server_name: string;
  mcp_config: Record<string, any>; // Raw mcp-use config
  display_name: string;
  description?: string;
  oauth_integration_id?: string;
}

export interface MCPServerStatus {
  server_name: string;
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
   * Get MCP server status for all templates
   */
  getMCPServersStatus: async (): Promise<MCPServerStatusSummary[]> => {
    try {
      const response = await apiService.get("/mcp/status");
      return (response as { servers: MCPServerStatusSummary[] }).servers;
    } catch (error) {
      console.error("Failed to get MCP servers status:", error);
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
  getMCPServer: async (serverName: string): Promise<MCPServer> => {
    try {
      const response = await apiService.get(`/mcp/servers/${serverName}`);
      return response as MCPServer;
    } catch (error) {
      console.error(`Failed to get MCP server ${serverName}:`, error);
      throw error;
    }
  },

  /**
   * Update MCP server
   */
  updateMCPServer: async (
    serverName: string,
    updates: Partial<MCPServerCreateRequest>,
  ): Promise<MCPServer> => {
    try {
      const response = await apiService.put(
        `/mcp/servers/${serverName}`,
        updates,
      );
      return response as MCPServer;
    } catch (error) {
      console.error(`Failed to update MCP server ${serverName}:`, error);
      throw error;
    }
  },

  /**
   * Delete MCP server
   */
  deleteMCPServer: async (serverName: string): Promise<void> => {
    try {
      await apiService.delete(`/mcp/servers/${serverName}`);
    } catch (error) {
      console.error(`Failed to delete MCP server ${serverName}:`, error);
      throw error;
    }
  },

  /**
   * Get MCP server connection status
   */
  getMCPServerStatus: async (serverName: string): Promise<MCPServerStatus> => {
    try {
      const response = await apiService.get(
        `/mcp/servers/${serverName}/status`,
      );
      return response as MCPServerStatus;
    } catch (error) {
      console.error(`Failed to get MCP server status ${serverName}:`, error);
      throw error;
    }
  },

  /**
   * Initiate OAuth for MCP server
   */
  initiateOAuth: async (
    serverName: string,
  ): Promise<{ authorization_url: string }> => {
    try {
      const response = await apiService.get(
        `/mcp/oauth/${serverName}/authorize`,
      );
      return response as { authorization_url: string };
    } catch (error) {
      console.error(`Failed to initiate OAuth for ${serverName}:`, error);
      throw error;
    }
  },
};

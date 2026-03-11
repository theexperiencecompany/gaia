/**
 * MCP proxy API types — mirroring the backend schemas/mcp request/response models.
 */

export interface MCPToolCallResult {
  content: Array<{ type: string; text?: string; [key: string]: unknown }>;
  is_error?: boolean;
}

export interface MCPResourcesListResult {
  resources: Array<{ uri: string; name: string; [key: string]: unknown }>;
  next_cursor?: string;
}

export interface MCPResourceTemplatesListResult {
  resource_templates: Array<{
    uriTemplate: string;
    name: string;
    [key: string]: unknown;
  }>;
  next_cursor?: string;
}

export interface MCPResourceReadResult {
  contents: Array<{
    uri: string;
    mimeType?: string;
    text?: string;
    blob?: string;
    [key: string]: unknown;
  }>;
}

export interface MCPPromptsListResult {
  prompts: Array<{
    name: string;
    description?: string;
    [key: string]: unknown;
  }>;
  next_cursor?: string;
}

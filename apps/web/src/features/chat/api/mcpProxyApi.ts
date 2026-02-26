import { apiauth } from "@/lib/api/client";

export interface MCPToolCallResult {
  content: Array<{ type: string; text?: string; [key: string]: unknown }>;
  is_error?: boolean;
}

export async function callMCPAppTool(
  serverUrl: string,
  toolName: string,
  args: Record<string, unknown>,
): Promise<MCPToolCallResult> {
  const response = await apiauth.post<MCPToolCallResult>(
    "/mcp/proxy/tool-call",
    {
      server_url: serverUrl,
      tool_name: toolName,
      arguments: args,
    },
  );
  return response.data;
}

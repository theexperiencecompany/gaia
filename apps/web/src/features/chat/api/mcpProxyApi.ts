import axios from "axios";
import type {
  MCPPromptsListResult,
  MCPResourceReadResult,
  MCPResourcesListResult,
  MCPResourceTemplatesListResult,
  MCPToolCallResult,
} from "@/features/chat/types/mcpProxy";
import { apiauth } from "@/lib/api/client";

export type {
  MCPPromptsListResult,
  MCPResourceReadResult,
  MCPResourcesListResult,
  MCPResourceTemplatesListResult,
  MCPToolCallResult,
} from "@/features/chat/types/mcpProxy";

function buildErrorResult(message: string): MCPToolCallResult {
  return {
    content: [{ type: "text", text: message }],
    is_error: true,
  };
}

function extractErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data;
    if (detail && typeof detail === "object" && "detail" in detail) {
      const value = detail.detail;
      if (typeof value === "string" && value.trim()) {
        return value;
      }
    }
    if (typeof detail === "string" && detail.trim()) {
      return detail;
    }
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "MCP tool call failed";
}

function normalizeToolArguments(args: unknown): Record<string, unknown> {
  if (args && typeof args === "object" && !Array.isArray(args)) {
    return args as Record<string, unknown>;
  }
  return {};
}

async function postProxy<T>(
  path: string,
  body: Record<string, unknown>,
): Promise<{ result?: T; error?: unknown }> {
  try {
    const response = await apiauth.post<T>(path, body);
    return { result: response.data };
  } catch (error) {
    return { error };
  }
}

export async function callMCPAppTool(
  integrationId: string,
  toolName: string,
  args: unknown,
): Promise<MCPToolCallResult> {
  const safeArgs = normalizeToolArguments(args);
  const { result, error } = await postProxy<MCPToolCallResult>(
    "/mcp/proxy/tool-call",
    {
      integration_id: integrationId,
      tool_name: toolName,
      arguments: safeArgs,
    },
  );
  if (result) return result;
  return buildErrorResult(extractErrorMessage(error));
}

export async function listMCPResources(
  integrationId: string,
  cursor?: string,
): Promise<MCPResourcesListResult> {
  const body: Record<string, unknown> = { integration_id: integrationId };
  if (cursor !== undefined) body.cursor = cursor;
  const { result, error } = await postProxy<MCPResourcesListResult>(
    "/mcp/proxy/resources/list",
    body,
  );
  if (result) return result;
  throw new Error(extractErrorMessage(error));
}

export async function listMCPResourceTemplates(
  integrationId: string,
  cursor?: string,
): Promise<MCPResourceTemplatesListResult> {
  const body: Record<string, unknown> = { integration_id: integrationId };
  if (cursor !== undefined) body.cursor = cursor;
  const { result, error } = await postProxy<MCPResourceTemplatesListResult>(
    "/mcp/proxy/resources/templates/list",
    body,
  );
  if (result) return result;
  throw new Error(extractErrorMessage(error));
}

export async function readMCPResource(
  integrationId: string,
  uri: string,
): Promise<MCPResourceReadResult> {
  const { result, error } = await postProxy<MCPResourceReadResult>(
    "/mcp/proxy/resources/read",
    { integration_id: integrationId, uri },
  );
  if (result) return result;
  throw new Error(extractErrorMessage(error));
}

export async function listMCPPrompts(
  integrationId: string,
  cursor?: string,
): Promise<MCPPromptsListResult> {
  const body: Record<string, unknown> = { integration_id: integrationId };
  if (cursor !== undefined) body.cursor = cursor;
  const { result, error } = await postProxy<MCPPromptsListResult>(
    "/mcp/proxy/prompts/list",
    body,
  );
  if (result) return result;
  throw new Error(extractErrorMessage(error));
}

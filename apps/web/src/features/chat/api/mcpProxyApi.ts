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

function getServerUrlCandidates(serverUrl: string): string[] {
  const trimmed = serverUrl.trim();
  if (!trimmed) return [serverUrl];

  const candidates = new Set<string>([trimmed]);
  try {
    const parsed = new URL(trimmed);
    const noSlash = parsed.toString().replace(/\/$/, "");
    const withSlash = `${noSlash}/`;
    candidates.add(noSlash);
    candidates.add(withSlash);
  } catch {
    candidates.add(trimmed.replace(/\/$/, ""));
    candidates.add(`${trimmed.replace(/\/$/, "")}/`);
  }
  return Array.from(candidates);
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

async function proxyAcrossCandidates<T>(
  serverUrl: string,
  path: string,
  body: Record<string, unknown>,
): Promise<{ result?: T; error?: unknown }> {
  let lastError: unknown = null;
  for (const candidateServerUrl of getServerUrlCandidates(serverUrl)) {
    try {
      const response = await apiauth.post<T>(path, {
        ...body,
        server_url: candidateServerUrl,
      });
      return { result: response.data };
    } catch (error) {
      lastError = error;
    }
  }
  return { error: lastError };
}

export async function callMCPAppTool(
  serverUrl: string,
  toolName: string,
  args: unknown,
): Promise<MCPToolCallResult> {
  const safeArgs = normalizeToolArguments(args);
  const { result, error } = await proxyAcrossCandidates<MCPToolCallResult>(
    serverUrl,
    "/mcp/proxy/tool-call",
    { tool_name: toolName, arguments: safeArgs },
  );
  if (result) return result;
  return buildErrorResult(extractErrorMessage(error));
}

export async function listMCPResources(
  serverUrl: string,
  cursor?: string,
): Promise<MCPResourcesListResult> {
  const body: Record<string, unknown> = {};
  if (cursor !== undefined) body.cursor = cursor;
  const { result, error } = await proxyAcrossCandidates<MCPResourcesListResult>(
    serverUrl,
    "/mcp/proxy/resources/list",
    body,
  );
  if (result) return result;
  throw new Error(extractErrorMessage(error));
}

export async function listMCPResourceTemplates(
  serverUrl: string,
  cursor?: string,
): Promise<MCPResourceTemplatesListResult> {
  const body: Record<string, unknown> = {};
  if (cursor !== undefined) body.cursor = cursor;
  const { result, error } =
    await proxyAcrossCandidates<MCPResourceTemplatesListResult>(
      serverUrl,
      "/mcp/proxy/resources/templates/list",
      body,
    );
  if (result) return result;
  throw new Error(extractErrorMessage(error));
}

export async function readMCPResource(
  serverUrl: string,
  uri: string,
): Promise<MCPResourceReadResult> {
  const { result, error } = await proxyAcrossCandidates<MCPResourceReadResult>(
    serverUrl,
    "/mcp/proxy/resources/read",
    { uri },
  );
  if (result) return result;
  throw new Error(extractErrorMessage(error));
}

export async function listMCPPrompts(
  serverUrl: string,
  cursor?: string,
): Promise<MCPPromptsListResult> {
  const body: Record<string, unknown> = {};
  if (cursor !== undefined) body.cursor = cursor;
  const { result, error } = await proxyAcrossCandidates<MCPPromptsListResult>(
    serverUrl,
    "/mcp/proxy/prompts/list",
    body,
  );
  if (result) return result;
  throw new Error(extractErrorMessage(error));
}

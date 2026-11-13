import { ApiError } from "@shared/api";
import type {
  MCPPromptsListResult,
  MCPResourceReadResult,
  MCPResourcesListResult,
  MCPResourceTemplatesListResult,
  MCPToolCallResult,
} from "@/features/chat/types/mcpProxy";
import { api } from "@/lib/api/typed";

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
  if (error instanceof ApiError) {
    return error.envelope?.message ?? error.message;
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

/**
 * Retry one proxy call across the server URL spellings an MCP server may
 * answer on (trailing slash or not), returning the first that succeeds.
 *
 * The item shapes the UI reads are narrower than the API's
 * `dict[str, Any]` lists, so the result is narrowed here rather than at every
 * field access.
 */
async function proxyAcrossCandidates<T>(
  serverUrl: string,
  send: (candidateServerUrl: string) => Promise<unknown>,
): Promise<{ result?: T; error?: unknown }> {
  let lastError: unknown = null;
  for (const candidateServerUrl of getServerUrlCandidates(serverUrl)) {
    try {
      return { result: (await send(candidateServerUrl)) as T };
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
  const { result, error } = await proxyAcrossCandidates<MCPToolCallResult>(
    serverUrl,
    (server_url) =>
      api.post("/api/v1/mcp/proxy/tool-call", {
        body: {
          server_url,
          tool_name: toolName,
          arguments: normalizeToolArguments(args),
        },
        silent: true,
      }),
  );
  if (result) return result;
  return buildErrorResult(extractErrorMessage(error));
}

export async function listMCPResources(
  serverUrl: string,
  cursor?: string,
): Promise<MCPResourcesListResult> {
  const { result, error } = await proxyAcrossCandidates<MCPResourcesListResult>(
    serverUrl,
    (server_url) =>
      api.post("/api/v1/mcp/proxy/resources/list", {
        body: { server_url, cursor },
        silent: true,
      }),
  );
  if (result) return result;
  throw new Error(extractErrorMessage(error));
}

export async function listMCPResourceTemplates(
  serverUrl: string,
  cursor?: string,
): Promise<MCPResourceTemplatesListResult> {
  const { result, error } =
    await proxyAcrossCandidates<MCPResourceTemplatesListResult>(
      serverUrl,
      (server_url) =>
        api.post("/api/v1/mcp/proxy/resources/templates/list", {
          body: { server_url, cursor },
          silent: true,
        }),
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
    (server_url) =>
      api.post("/api/v1/mcp/proxy/resources/read", {
        body: { server_url, uri },
        silent: true,
      }),
  );
  if (result) return result;
  throw new Error(extractErrorMessage(error));
}

export async function listMCPPrompts(
  serverUrl: string,
  cursor?: string,
): Promise<MCPPromptsListResult> {
  const { result, error } = await proxyAcrossCandidates<MCPPromptsListResult>(
    serverUrl,
    (server_url) =>
      api.post("/api/v1/mcp/proxy/prompts/list", {
        body: { server_url, cursor },
        silent: true,
      }),
  );
  if (result) return result;
  throw new Error(extractErrorMessage(error));
}

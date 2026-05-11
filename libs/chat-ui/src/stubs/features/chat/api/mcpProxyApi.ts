/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 *
 * NOTE: Source file in apps/web is `mcpProxyApi.ts`. The task list referred to
 * this as `mcpPro.ts` — the actual filename is `mcpProxyApi.ts`. Stubbed here
 * under the real name for path-alias parity.
 */
import type {
  MCPPromptsListResult,
  MCPResourceReadResult,
  MCPResourcesListResult,
  MCPResourceTemplatesListResult,
  MCPToolCallResult,
} from "@/features/chat/types/mcpProxy";

export type {
  MCPPromptsListResult,
  MCPResourceReadResult,
  MCPResourcesListResult,
  MCPResourceTemplatesListResult,
  MCPToolCallResult,
} from "@/features/chat/types/mcpProxy";

const emptyToolResult = (): MCPToolCallResult => ({
  content: [{ type: "text", text: "" }],
  is_error: false,
});

export async function callMCPAppTool(
  _serverUrl: string,
  _toolName: string,
  _args: unknown,
): Promise<MCPToolCallResult> {
  return emptyToolResult();
}

export async function listMCPResources(
  _serverUrl: string,
  _cursor?: string,
): Promise<MCPResourcesListResult> {
  return {} as MCPResourcesListResult;
}

export async function listMCPResourceTemplates(
  _serverUrl: string,
  _cursor?: string,
): Promise<MCPResourceTemplatesListResult> {
  return {} as MCPResourceTemplatesListResult;
}

export async function readMCPResource(
  _serverUrl: string,
  _uri: string,
): Promise<MCPResourceReadResult> {
  return {} as MCPResourceReadResult;
}

export async function listMCPPrompts(
  _serverUrl: string,
  _cursor?: string,
): Promise<MCPPromptsListResult> {
  return {} as MCPPromptsListResult;
}

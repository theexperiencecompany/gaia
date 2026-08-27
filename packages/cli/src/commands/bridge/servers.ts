// Builds a raw MCP Transport for one exposed server. The tunnel relays JSON-RPC
// frames straight through this transport:
//   - stdio  → we spawn the server command as a child process (the common case
//              for local servers like GitHub's — the user never runs it manually)
//   - url    → HTTP client transport to a server already listening on localhost
//   - filesystem → in-memory pair to the built-in filesystem McpServer

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import {
  getDefaultEnvironment,
  StdioClientTransport,
} from "@modelcontextprotocol/sdk/client/stdio.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import type { Transport } from "@modelcontextprotocol/sdk/shared/transport.js";
import type { ServerConfig } from "./config.types.js";
import { buildFilesystemServer } from "./filesystem-server.js";

export interface ServerSession {
  transport: Transport;
  close: () => Promise<void>;
}

export async function openServerSession(
  config: ServerConfig,
): Promise<ServerSession> {
  if (config.type === "url") {
    const transport = new StreamableHTTPClientTransport(new URL(config.url));
    // StreamableHTTPClientTransport declares `get sessionId(): string | undefined`
    // where the SDK's own Transport interface types it as the optional `sessionId?:
    // string` — a mismatch that only surfaces under exactOptionalPropertyTypes, not
    // a real behavioral difference (both mean "may be absent").
    return {
      transport: transport as unknown as Transport,
      close: () => transport.close(),
    };
  }

  if (config.type === "stdio") {
    const transport = new StdioClientTransport({
      command: config.command,
      args: config.args,
      env: { ...getDefaultEnvironment(), ...config.env },
    });
    return { transport, close: () => transport.close() };
  }

  const [clientTransport, serverTransport] =
    InMemoryTransport.createLinkedPair();
  const mcpServer = buildFilesystemServer(config);
  await mcpServer.connect(serverTransport);
  return {
    transport: clientTransport,
    close: async () => {
      await mcpServer.close();
      await clientTransport.close();
    },
  };
}

/** Connect to a configured server locally and list its tools — the wizard's preflight. */
export async function testServer(config: ServerConfig): Promise<string[]> {
  const session = await openServerSession(config);
  const client = new Client({ name: "gaia-bridge-test", version: "0.1.0" });
  try {
    await client.connect(session.transport);
    const { tools } = await client.listTools();
    return tools.map((t) => t.name);
  } finally {
    try {
      await client.close();
      await session.close();
    } catch {
      // best-effort teardown; the result/error above is what matters
    }
  }
}

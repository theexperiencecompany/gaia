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
import { bridgeEnv } from "./env.js";
import { buildFilesystemServer } from "./filesystem-server.js";

export interface ServerSession {
  transport: Transport;
  close: () => Promise<void>;
}

const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1", "::1"]);

/** How many same-origin redirect hops the guarded fetch follows before giving
 * up. Redirect chains longer than this are a misconfiguration, not a server. */
const MAX_REDIRECT_HOPS = 5;

/** A url server must point at THIS machine, or the cloud could drive the daemon
 * into the user's LAN (SSRF pivot). Config is user-editable, so guard on open. */
export function assertLoopbackUrl(raw: string): URL {
  const url = new URL(raw);
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error(`url servers must be http(s), got ${url.protocol}`);
  }
  const host = url.hostname.replace(/^\[|\]$/g, "");
  if (!LOOPBACK_HOSTS.has(host)) {
    throw new Error(
      "url servers must point at this machine (localhost / 127.0.0.1 / ::1)",
    );
  }
  return url;
}

function requestUrl(input: string | URL | Request): URL {
  return new URL(
    typeof input === "string"
      ? input
      : input instanceof URL
        ? input.href
        : input.url,
  );
}

/** fetch wrapper that refuses to forward (possibly credential-bearing) headers
 * across origins. The MCP SDK follows redirects by default, and its
 * `requestInit.redirect` never reaches the initial GET on 1.29.0 — so the
 * policy lives here, where every request path (GET/POST/DELETE) flows through
 * the injected `fetch`. Same-origin hops (e.g. / → /mcp on one host) are
 * followed; anything else throws instead of leaking headers to it. */
export async function guardedFetch(
  input: string | URL | Request,
  init?: RequestInit,
): Promise<Response> {
  let current = requestUrl(input);
  let requestInit: RequestInit | undefined = { ...init, redirect: "manual" };
  for (let hop = 0; ; hop++) {
    const response = await fetch(current, requestInit);
    if (response.status < 300 || response.status >= 400) return response;
    const location = response.headers.get("location");
    const next = location ? new URL(location, current.href) : null;
    await response.body?.cancel();
    if (!next || next.origin !== current.origin) {
      throw new Error(
        `refusing ${response.status} redirect to ${location ?? "(no location)"} — ` +
          "an MCP server must be addressed directly, not via a redirect",
      );
    }
    if (hop >= MAX_REDIRECT_HOPS) {
      throw new Error(
        `too many redirects (>${MAX_REDIRECT_HOPS}) — refusing to follow`,
      );
    }
    current = next;
    // Same `init` is reusable for the next hop: the SDK only ever sends string
    // bodies (JSON), which — unlike streams — survive being sent twice.
    requestInit = { ...init, redirect: "manual" };
  }
}

export async function openServerSession(
  config: ServerConfig,
): Promise<ServerSession> {
  if (config.type === "url") {
    const url = assertLoopbackUrl(config.url);
    // The SDK's requestInit.redirect never reaches its initial GET (1.29.0),
    // so redirect policy is enforced by the injected fetch on every path.
    const transport = new StreamableHTTPClientTransport(url, {
      requestInit: { ...(config.headers ? { headers: config.headers } : {}) },
      fetch: guardedFetch,
    });
    // StreamableHTTPClientTransport's `sessionId` getter type mismatches the
    // SDK's own optional `sessionId?` under exactOptionalPropertyTypes only —
    // not a real behavioral difference; both mean "may be absent".
    return {
      transport: transport as unknown as Transport,
      close: () => transport.close(),
    };
  }

  if (config.type === "stdio") {
    // Overrides getDefaultEnvironment()'s PATH/HOME with the host's resolved
    // ones — a Finder-launched app has a bare PATH that ENOENTs npx/uvx/node.
    // Only these two are lifted, to keep the safe-subset env filtering intact.
    const injected = bridgeEnv().env;
    const transport = new StdioClientTransport({
      command: config.command,
      args: config.args,
      env: {
        ...getDefaultEnvironment(),
        ...(injected["PATH"] !== undefined ? { PATH: injected["PATH"] } : {}),
        ...(injected["HOME"] !== undefined ? { HOME: injected["HOME"] } : {}),
        ...config.env,
      },
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

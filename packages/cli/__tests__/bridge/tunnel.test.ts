import { beforeEach, describe, expect, it, vi } from "vitest";
import WebSocket from "ws";

import { FRAME } from "../../src/commands/bridge/constants.js";

// loadConfig reads the on-disk config; stub it so openSession resolves the
// server by key without touching the filesystem.
vi.mock("../../src/commands/bridge/config.js", () => ({
  loadConfig: vi.fn(() => ({
    servers: [
      {
        type: "url",
        key: "local-http",
        name: "Local HTTP",
        url: "http://127.0.0.1:9/mcp",
      },
    ],
  })),
  saveCredentials: vi.fn(),
}));

// openServerSession would spawn a child / dial a URL; return a fake transport
// whose onerror we can fire by hand.
vi.mock("../../src/commands/bridge/servers.js", () => ({
  openServerSession: vi.fn(),
}));

import { openServerSession } from "../../src/commands/bridge/servers.js";
import { Tunnel } from "../../src/commands/bridge/tunnel.js";

const mockedOpen = vi.mocked(openServerSession);

function makeTransport() {
  return {
    start: vi.fn().mockResolvedValue(undefined),
    send: vi.fn(),
    close: vi.fn().mockResolvedValue(undefined),
    onmessage: undefined as ((message: unknown) => void) | undefined,
    onclose: undefined as (() => void) | undefined,
    onerror: undefined as ((error: Error) => void) | undefined,
  };
}

function makeFakeWs() {
  return {
    readyState: WebSocket.OPEN,
    send: vi.fn(),
    close: vi.fn(),
  };
}

function sentFrames(ws: ReturnType<typeof makeFakeWs>) {
  return ws.send.mock.calls.map((call) => JSON.parse(call[0] as string));
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Tunnel session error handling", () => {
  it("surfaces a transport error as mcp.error so a url-server drop can't hang the call", async () => {
    const transport = makeTransport();
    const session = { transport, close: vi.fn().mockResolvedValue(undefined) };
    mockedOpen.mockResolvedValue(session as never);

    const tunnel = new Tunnel({
      apiUrl: "http://gaia.test",
      deviceId: "dev-1",
      refreshToken: "r",
    });
    const ws = makeFakeWs();
    (tunnel as unknown as { ws: unknown }).ws = ws;

    await (
      tunnel as unknown as { onFrame: (raw: string) => Promise<void> }
    ).onFrame(
      JSON.stringify({
        t: FRAME.MCP_OPEN,
        sid: "s1",
        server: "local-http",
        pod: "pod-1",
      }),
    );

    // The regression: onerror must be wired. A url transport reports a dropped
    // connection here and does not always follow with onclose.
    expect(transport.onerror).toBeTypeOf("function");

    transport.onerror?.(new Error("connection reset"));

    const errorFrame = sentFrames(ws).find(
      (frame) => frame.t === FRAME.MCP_ERROR,
    );
    expect(errorFrame).toBeDefined();
    expect(errorFrame.sid).toBe("s1");
    expect(errorFrame.pod).toBe("pod-1");
    expect(errorFrame.error).toContain("connection reset");
  });
});

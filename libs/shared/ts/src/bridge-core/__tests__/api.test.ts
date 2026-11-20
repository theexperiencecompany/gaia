import {
  createServer,
  type IncomingMessage,
  type ServerResponse,
} from "node:http";
import type { AddressInfo } from "node:net";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { startPairing } from "../api.js";
import { configureBridge } from "../env.js";

interface TestServer {
  url: string;
  requests: string[];
  close(): Promise<void>;
}

const servers: TestServer[] = [];

/** A real loopback server: the client's fetch, parsing and logging run for real. */
async function serve(
  handler: (req: IncomingMessage, res: ServerResponse) => void,
): Promise<TestServer> {
  const requests: string[] = [];
  const server = createServer((req, res) => {
    requests.push(req.url ?? "");
    req.resume();
    handler(req, res);
  });
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, resolve);
  });
  const { port } = server.address() as AddressInfo;
  const started: TestServer = {
    url: `http://localhost:${port}`,
    requests,
    close: () =>
      new Promise<void>((resolve, reject) => {
        server.close((error) => (error ? reject(error) : resolve()));
      }),
  };
  servers.push(started);
  return started;
}

const logs = { info: vi.fn(), error: vi.fn() };

beforeEach(() => {
  configureBridge({ logger: logs });
});

afterEach(async () => {
  for (const started of servers.splice(0)) await started.close();
  logs.info.mockReset();
  logs.error.mockReset();
});

describe("startPairing", () => {
  it("names the URL and the media type when the answer isn't the API's own error", async () => {
    const server = await serve((_req, res) => {
      res.writeHead(404, { "content-type": "text/html; charset=utf-8" });
      res.end("<!DOCTYPE html><title>404</title>");
    });

    await expect(
      startPairing(server.url, "dev", "darwin", "0.7.0"),
    ).rejects.toThrow(
      `404 Not Found from ${server.url}/api/v1/device/pair/start (text/html) — not the GAIA API's JSON error body`,
    );
  });

  it("names the gateway that answered after a redirect, and where the request went", async () => {
    const gateway = await serve((_req, res) => {
      res.writeHead(403, { "content-type": "text/html" });
      res.end("<html>forbidden</html>");
    });
    const front = await serve((req, res) => {
      res.writeHead(302, { location: `${gateway.url}${req.url}` });
      res.end();
    });

    await expect(
      startPairing(front.url, "dev", "darwin", "0.7.0"),
    ).rejects.toThrow(
      `403 Forbidden from ${gateway.url}/api/v1/device/pair/start (text/html) — not the GAIA API's JSON error body; the request went to ${front.url}/api/v1/device/pair/start`,
    );
  });

  it("records a foreign answer for the daemon's log", async () => {
    const server = await serve((_req, res) => {
      res.writeHead(502, { "content-type": "text/html" });
      res.end("<html>bad gateway</html>");
    });

    await expect(
      startPairing(server.url, "dev", "darwin", "0.7.0"),
    ).rejects.toThrow();

    expect(logs.error).toHaveBeenCalledWith(
      "[gaia bridge] POST /api/v1/device/pair/start → 502 text/html, not GAIA's envelope",
      {
        url: `${server.url}/api/v1/device/pair/start`,
        requestedUrl: `${server.url}/api/v1/device/pair/start`,
        status: 502,
        contentType: "text/html",
        requestId: undefined,
        body: "<html>bad gateway</html>",
      },
    );
  });

  it("keeps the API's own words when it sent an envelope", async () => {
    const server = await serve((_req, res) => {
      res.writeHead(403, { "content-type": "application/json" });
      res.end(JSON.stringify({ message: "pairing is closed", code: "closed" }));
    });

    await expect(
      startPairing(server.url, "dev", "darwin", "0.7.0"),
    ).rejects.toThrow(/^pairing is closed$/);
    expect(logs.error).not.toHaveBeenCalled();
  });
});

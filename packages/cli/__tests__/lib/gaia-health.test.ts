import { afterEach, describe, expect, it } from "vitest";

import { probeGaia } from "../../src/lib/gaia-health.js";
import {
  closedPort,
  sendHtml,
  sendJson,
  startTestServer,
  type TestServer,
} from "../helpers/test-server.js";

const GAIA_ONLINE = {
  status: "online",
  message: "GAIA API is online",
  name: "GAIA",
  version: "1.2.3",
  description: "Your proactive personal assistant",
  environment: "selfhost",
  commit: "abc1234",
  event_loop_lag_ms: 1.2,
};

const GAIA_DEGRADED = {
  status: "degraded",
  event_loop_lag_ms: 812.5,
  detail: "event loop lag is above the threshold",
};

const servers: TestServer[] = [];
async function serve(
  handler: Parameters<typeof startTestServer>[0],
): Promise<TestServer> {
  const started = await startTestServer(handler);
  servers.push(started);
  return started;
}

afterEach(async () => {
  for (const started of servers.splice(0)) await started.close();
});

describe("probeGaia", () => {
  it("reads GAIA's online health body", async () => {
    const server = await serve((_req, res) => sendJson(res, GAIA_ONLINE));

    expect(await probeGaia(`${server.url}/api/v1`)).toEqual({
      kind: "gaia",
      degraded: false,
    });
    expect(server.requests).toEqual(["/api/v1/ping"]);
  });

  it("reads GAIA's 503 degraded answer as GAIA, degraded", async () => {
    const server = await serve((_req, res) =>
      sendJson(res, GAIA_DEGRADED, 503),
    );

    expect(await probeGaia(`${server.url}/api/v1`)).toEqual({
      kind: "gaia",
      degraded: true,
    });
  });

  it("reports a web server's HTML 404 as something else", async () => {
    const server = await serve((_req, res) => sendHtml(res, 404));

    expect(await probeGaia(`${server.url}/api/v1`)).toEqual({
      kind: "other",
      status: 404,
      contentType: "text/html",
    });
  });

  it("reports a JSON server that isn't GAIA as something else", async () => {
    const server = await serve((_req, res) => sendJson(res, { ok: true }));

    expect(await probeGaia(`${server.url}/api/v1`)).toEqual({
      kind: "other",
      status: 200,
      contentType: "application/json",
    });
  });

  it("refuses a health body that arrived through another origin", async () => {
    const real = await serve((_req, res) => sendJson(res, GAIA_ONLINE));
    const redirecting = await serve((_req, res) => {
      res.writeHead(302, { location: `${real.url}/api/v1/ping` });
      res.end();
    });

    expect(await probeGaia(`${redirecting.url}/api/v1`)).toEqual({
      kind: "other",
      status: 200,
      contentType: "application/json",
      redirectedTo: `${real.url}/api/v1/ping`,
    });
  });

  it("reports a closed port as unreachable", async () => {
    const port = await closedPort();

    expect(await probeGaia(`http://localhost:${port}/api/v1`)).toEqual({
      kind: "unreachable",
    });
  });
});

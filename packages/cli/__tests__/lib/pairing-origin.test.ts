import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  notServingHelp,
  notServingPrompt,
  selfhostPairing,
} from "../../src/lib/pairing-origin.js";
import {
  closedPort,
  sendHtml,
  sendJson,
  startTestServer,
  type TestServer,
} from "../helpers/test-server.js";

const config = vi.hoisted(() => ({ setupComplete: true }));

vi.mock("../../src/lib/config.js", () => ({
  readConfig: () => ({ setupComplete: config.setupComplete }),
}));

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

const tempDirs: string[] = [];
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
  config.setupComplete = true;
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

/** A self-host install that records WEB_HOST_PORT, as `gaia up` writes it. */
function installWithPort(port: number): string {
  const repo = mkdtempSync(join(tmpdir(), "gaia-install-"));
  tempDirs.push(repo);
  mkdirSync(join(repo, "packages", "cli", "selfhost"), { recursive: true });
  writeFileSync(
    join(repo, "packages", "cli", "selfhost", ".env"),
    `WEB_HOST_PORT=${port}\n`,
  );
  return repo;
}

describe("selfhostPairing", () => {
  it("serves the install's origin once GAIA answers there", async () => {
    const server = await serve((_req, res) => sendJson(res, GAIA_ONLINE));

    expect(await selfhostPairing(installWithPort(server.port))).toEqual({
      kind: "serving",
      origin: `http://localhost:${server.port}`,
    });
    expect(server.requests).toEqual(["/api/v1/ping"]);
  });

  it("probes the port the install records", async () => {
    const server = await serve((_req, res) => sendJson(res, GAIA_ONLINE));
    const repo = installWithPort(server.port);

    await selfhostPairing(repo);

    expect(server.requests).toEqual(["/api/v1/ping"]);
  });

  it("reports what answered when it isn't GAIA", async () => {
    const server = await serve((_req, res) => sendHtml(res, 502));
    const repo = installWithPort(server.port);

    const pairing = await selfhostPairing(repo);
    expect(pairing).toMatchObject({
      kind: "not-serving",
      origin: `http://localhost:${server.port}`,
      finishedSetup: true,
      health: { kind: "other", status: 502, contentType: "text/html" },
    });
    if (pairing.kind !== "not-serving") throw new Error("expected not-serving");

    const help = notServingHelp(pairing);
    expect(help).toContain(
      `answered HTTP 502 (text/html) at http://localhost:${server.port}`,
    );
    expect(help).toContain("another program holds that port");
    expect(help).toContain("--api https://api.heygaia.io");
  });

  it("refuses an install whose health probe redirects to another origin", async () => {
    const real = await serve((_req, res) => sendJson(res, GAIA_ONLINE));
    const redirecting = await serve((_req, res) => {
      res.writeHead(302, { location: `${real.url}/api/v1/ping` });
      res.end();
    });

    const pairing = await selfhostPairing(installWithPort(redirecting.port));
    if (pairing.kind !== "not-serving") throw new Error("expected not-serving");
    if (pairing.health.kind !== "other") throw new Error("expected other");

    expect(pairing.health.redirectedTo).toBe(`${real.url}/api/v1/ping`);
    const help = notServingHelp(pairing);
    expect(help).toContain("redirected");
    expect(help).toContain(`${real.url}/api/v1/ping`);
    expect(help).toContain("--api https://api.heygaia.io");
  });

  it("tells a finished install to start and an unfinished one to finish", async () => {
    const port = await closedPort();
    const repo = installWithPort(port);
    const base = await selfhostPairing(repo);
    if (base.kind !== "not-serving") throw new Error("expected not-serving");

    expect(base.health).toEqual({ kind: "unreachable" });
    expect(notServingHelp(base)).toContain("Start it with 'gaia start'");
    expect(notServingPrompt(base)).not.toContain("never finished");

    config.setupComplete = false;
    const unfinished = await selfhostPairing(repo);
    if (unfinished.kind !== "not-serving") {
      throw new Error("expected not-serving");
    }
    expect(unfinished.finishedSetup).toBe(false);
    expect(notServingHelp(unfinished)).toContain(
      "Finish setting it up with 'gaia up'",
    );
    expect(notServingPrompt(unfinished)).toContain(
      "it never finished setting up",
    );
  });
});

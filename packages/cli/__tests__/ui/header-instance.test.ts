import * as fs from "node:fs";
import * as http from "node:http";
import type { AddressInfo } from "node:net";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { findInstallRoot, cachedLatestRelease, refreshLatestRelease } =
  vi.hoisted(() => ({
    findInstallRoot: vi.fn(),
    cachedLatestRelease: vi.fn(),
    refreshLatestRelease: vi.fn(),
  }));
vi.mock("../../src/lib/service-starter.js", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  findInstallRoot,
}));
vi.mock("../../src/lib/update-check.js", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  cachedLatestRelease,
  refreshLatestRelease,
}));

import {
  availableUpdate,
  probeInstance,
} from "../../src/ui/header/instance.js";

let root: string;
let server: http.Server | null = null;

/** A self-host install whose web port is `port` and whose images are pinned to `version`. */
function install(port: number, version = "v0.6.0"): string {
  fs.mkdirSync(path.join(root, "apps/api"), { recursive: true });
  fs.mkdirSync(path.join(root, "infra/docker"), { recursive: true });
  fs.writeFileSync(path.join(root, "apps/api/.env"), "SETUP_MODE=selfhost\n");
  fs.writeFileSync(
    path.join(root, "infra/docker/.env"),
    `WEB_HOST_PORT=${port}\nGAIA_DOMAIN=gaia.test\nGAIA_VERSION=${version}\n`,
  );
  findInstallRoot.mockReturnValue(root);
  return root;
}

/** A local API answering the setup endpoints with these bodies. */
async function serve(
  routes: Record<string, unknown>,
  delayMs = 0,
): Promise<number> {
  server = http.createServer((req, res) => {
    const body = routes[req.url ?? ""];
    setTimeout(() => {
      if (body === undefined) {
        res.writeHead(404).end();
        return;
      }
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify(body));
    }, delayMs);
  });
  await new Promise<void>((resolve) => server?.listen(0, resolve));
  return (server.address() as AddressInfo).port;
}

const STATUS = "/api/v1/setup/status";
const CATALOG = "/api/v1/setup/catalog";

function statusBody(inUse: string[]): object {
  return {
    features: { ai_models: { available: true, working: true, in_use: inUse } },
  };
}

beforeEach(() => {
  root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "gaia-hdr-")));
  findInstallRoot.mockReset();
  cachedLatestRelease.mockReset();
  refreshLatestRelease.mockReset().mockResolvedValue(null);
});

afterEach(async () => {
  server?.closeAllConnections();
  await new Promise<void>((resolve) =>
    server ? server.close(() => resolve()) : resolve(),
  );
  server = null;
  fs.rmSync(root, { recursive: true, force: true });
});

describe("probeInstance", () => {
  it("reports where GAIA runs and its provider's catalog name", async () => {
    const port = await serve({
      [STATUS]: statusBody(["openrouter", "openai"]),
      [CATALOG]: { providers: { openrouter: { label: "OpenRouter" } } },
    });
    install(port);
    expect(await probeInstance()).toEqual({
      running: true,
      webUrl: "https://gaia.test",
      provider: "OpenRouter",
    });
  });

  it("leaves the provider out when no chat provider serves", async () => {
    const port = await serve({
      [STATUS]: statusBody([]),
      [CATALOG]: { providers: {} },
    });
    install(port);
    expect(await probeInstance()).toMatchObject({
      running: true,
      provider: null,
    });
  });

  it("is not running when nothing answers on the port", async () => {
    const port = await serve({});
    install(port);
    expect(await probeInstance()).toEqual({ running: false, installed: true });
  });

  it("gives up on a hung API within a fraction of a second", async () => {
    const port = await serve({ [STATUS]: statusBody([]) }, 5_000);
    install(port);
    const started = Date.now();
    expect(await probeInstance()).toEqual({ running: false, installed: true });
    expect(Date.now() - started).toBeLessThan(1_000);
  });

  it("says not installed, not just not running, when GAIA is not installed", async () => {
    findInstallRoot.mockReturnValue(null);
    expect(await probeInstance()).toEqual({ running: false, installed: false });
  });
});

describe("availableUpdate", () => {
  it("offers a cached release newer than the pinned one", () => {
    install(3000, "v0.6.0");
    cachedLatestRelease.mockReturnValue("v0.7.0");
    expect(availableUpdate()).toBe("v0.7.0");
    expect(refreshLatestRelease).toHaveBeenCalledOnce();
  });

  it("offers nothing when the pinned release is current", () => {
    install(3000, "v0.7.0");
    cachedLatestRelease.mockReturnValue("v0.7.0");
    expect(availableUpdate()).toBeNull();
  });

  it("offers nothing to a development build", () => {
    install(3000, "latest");
    cachedLatestRelease.mockReturnValue("v0.7.0");
    expect(availableUpdate()).toBeNull();
  });

  it("offers nothing before any check has answered", () => {
    install(3000);
    cachedLatestRelease.mockReturnValue(null);
    expect(availableUpdate()).toBeNull();
  });
});

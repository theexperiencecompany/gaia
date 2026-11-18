import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { runLogin } from "../../src/commands/bridge/login.js";
import {
  closedPort,
  sendHtml,
  sendJson,
  startTestServer,
  type TestServer,
} from "../helpers/test-server.js";

const core = vi.hoisted(() => ({ runLogin: vi.fn() }));
const install = vi.hoisted(() => ({ root: "" }));
const tty = vi.hoisted(() => ({ interactive: true }));
const prompt = vi.hoisted(() => ({ confirm: vi.fn() }));

vi.mock("@gaia/shared/bridge-core/login", () => ({
  isPaired: () => false,
  runLogin: core.runLogin,
}));

vi.mock("../../src/lib/install-root.js", () => ({
  findInstallRoot: () => install.root,
  detectSetupMode: async () => "selfhost",
}));

vi.mock("../../src/lib/config.js", () => ({
  readConfig: () => ({ setupComplete: true }),
}));

vi.mock("../../src/lib/non-tty.js", () => ({
  isInteractive: () => tty.interactive,
}));

vi.mock("../../src/lib/prompt.js", () => ({
  confirm: prompt.confirm,
}));

const GAIA_ONLINE = {
  status: "online",
  version: "1.2.3",
  event_loop_lag_ms: 1.2,
};

const tempDirs: string[] = [];
let server: TestServer | undefined;

/** runLogin() skips the self-host probe when GAIA_API_URL is set, so a developer
 * shell that exports it would exercise a different path than CI does. */
const inheritedApiUrl = process.env["GAIA_API_URL"];

beforeEach(() => {
  delete process.env["GAIA_API_URL"];
  tty.interactive = true;
  prompt.confirm.mockResolvedValue(true);
});

afterEach(async () => {
  await server?.close();
  server = undefined;
  core.runLogin.mockReset();
  prompt.confirm.mockReset();
  if (inheritedApiUrl === undefined) {
    delete process.env["GAIA_API_URL"];
  } else {
    process.env["GAIA_API_URL"] = inheritedApiUrl;
  }
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

function installWithPort(port: number): string {
  const repo = mkdtempSync(join(tmpdir(), "gaia-install-"));
  tempDirs.push(repo);
  mkdirSync(join(repo, "packages", "cli", "selfhost"), { recursive: true });
  writeFileSync(
    join(repo, "packages", "cli", "selfhost", ".env"),
    `WEB_HOST_PORT=${port}\n`,
  );
  install.root = repo;
  return repo;
}

const pairingTarget = () => core.runLogin.mock.calls[0]?.[1];

describe("runLogin", () => {
  it("pairs with the self-host install once GAIA answers there", async () => {
    server = await startTestServer((_req, res) => sendJson(res, GAIA_ONLINE));
    installWithPort(server.port);

    await runLogin();

    expect(pairingTarget()).toEqual(
      expect.objectContaining({ api: `http://localhost:${server.port}` }),
    );
    expect(prompt.confirm).not.toHaveBeenCalled();
  });

  it("pairs with GAIA Cloud when the user agrees the install isn't usable", async () => {
    server = await startTestServer((_req, res) => sendHtml(res, 404));
    installWithPort(server.port);

    await runLogin();

    expect(prompt.confirm).toHaveBeenCalledOnce();
    expect(prompt.confirm.mock.calls[0]?.[0]).toContain(
      "Pair with GAIA Cloud instead?",
    );
    expect(pairingTarget()).toEqual(
      expect.objectContaining({ api: "https://api.heygaia.io" }),
    );
  });

  it("stops with the help when the user declines", async () => {
    server = await startTestServer((_req, res) => sendHtml(res, 502));
    installWithPort(server.port);
    prompt.confirm.mockResolvedValue(false);

    await expect(runLogin()).rejects.toThrow(
      /answered HTTP 502 \(text\/html\)/,
    );
    expect(core.runLogin).not.toHaveBeenCalled();
  });

  it("asks nothing where it cannot prompt, and stops with the help", async () => {
    const port = await closedPort();
    installWithPort(port);
    tty.interactive = false;

    await expect(runLogin()).rejects.toThrow(
      /isn't answering at http:\/\/localhost:\d+/,
    );
    expect(prompt.confirm).not.toHaveBeenCalled();
    expect(core.runLogin).not.toHaveBeenCalled();
  });

  it("uses an explicit --api without probing the install", async () => {
    server = await startTestServer((_req, res) => sendHtml(res, 500));
    installWithPort(server.port);

    await runLogin({ api: "https://api.heygaia.io" });

    expect(server.requests).toEqual([]);
    expect(pairingTarget()).toEqual(
      expect.objectContaining({ api: "https://api.heygaia.io" }),
    );
  });
});

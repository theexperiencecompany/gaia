import { randomUUID } from "node:crypto";
import { existsSync, readdirSync, statSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// env.ts holds a module-level override map, so each test must start from a
// clean module registry — otherwise a configureBridge() in one test leaks into
// the next. Re-import both modules fresh after vi.resetModules().
async function freshModules() {
  vi.resetModules();
  const env = await import("../env.js");
  const config = await import("../config.js");
  return { ...env, ...config };
}

const CLI_DEFAULT_DIR = join(homedir(), ".gaia", "bridge");

/** Files under ~/.gaia/bridge right now (empty list if the dir is absent). The
 * CLI may have real creds there; we assert the SET is unchanged, not empty. */
function cliDirSnapshot(): string[] {
  if (!existsSync(CLI_DEFAULT_DIR)) return [];
  return readdirSync(CLI_DEFAULT_DIR).sort();
}

const mode = (path: string) => statSync(path).mode & 0o777;

describe("bridge-core env injection", () => {
  let stateDir: string;

  beforeEach(() => {
    stateDir = join(tmpdir(), `gaia-bridge-test-${randomUUID()}`);
  });

  afterEach(() => {
    vi.resetModules();
  });

  it("round-trips credentials + config into the injected stateDir with 0700/0600 perms", async () => {
    const {
      configureBridge,
      saveCredentials,
      loadCredentials,
      loadConfig,
      filesystemServer,
      upsertServer,
    } = await freshModules();

    const before = cliDirSnapshot();

    configureBridge({ stateDir });

    const creds = {
      apiUrl: "https://api.example.test",
      deviceId: "dev-123",
      refreshToken: "secret-refresh-token",
    };
    saveCredentials(creds);
    upsertServer(filesystemServer(["/tmp"], false));

    // Written into the injected dir, not the CLI default.
    const credPath = join(stateDir, "credentials.json");
    const configPath = join(stateDir, "config.json");
    expect(existsSync(credPath)).toBe(true);
    expect(existsSync(configPath)).toBe(true);

    // Round-trips back out of the injected dir.
    expect(loadCredentials()).toEqual(creds);
    expect(loadConfig().servers).toContainEqual(
      filesystemServer(["/tmp"], false),
    );

    // Perms: dir 0700, credentials file 0600.
    expect(mode(stateDir)).toBe(0o700);
    expect(mode(credPath)).toBe(0o600);

    // Nothing leaked under ~/.gaia — the CLI default dir is untouched.
    expect(cliDirSnapshot()).toEqual(before);
  });

  it("bridgeEnv() falls back to CLI defaults when unconfigured", async () => {
    const { bridgeEnv } = await freshModules();

    const env = bridgeEnv();
    expect(env.stateDir).toBe(CLI_DEFAULT_DIR);
    expect(env.env).toBe(process.env);
    expect(env.shell).toBe(process.env.SHELL ?? "/bin/sh");
    expect(typeof env.shell).toBe("string");
    expect(env.shell.length).toBeGreaterThan(0);
  });

  it("configureBridge() merges — later calls keep earlier fields", async () => {
    const { configureBridge, bridgeEnv } = await freshModules();

    configureBridge({ stateDir });
    configureBridge({ shell: "/bin/zsh" });

    const env = bridgeEnv();
    expect(env.stateDir).toBe(stateDir);
    expect(env.shell).toBe("/bin/zsh");
    // Unset field still resolves to the default.
    expect(env.env).toBe(process.env);
  });
});

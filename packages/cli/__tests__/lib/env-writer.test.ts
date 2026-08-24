import {
  chmodSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  writeDockerComposeEnv,
  writeEnvFile,
  writeWebEnvFile,
} from "../../src/lib/env-writer.js";

/** Owner read/write only — env files carry generated machine secrets. */
const OWNER_ONLY = 0o600;

describe("env-writer file permissions", () => {
  const dirs: string[] = [];

  afterEach(() => {
    for (const dir of dirs.splice(0)) {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  function makeRepo(): string {
    const dir = mkdtempSync(path.join(tmpdir(), "gaia-env-writer-"));
    // Mirror a real clone's layout: the writers expect these directories.
    mkdirSync(path.join(dir, "apps", "api"), { recursive: true });
    mkdirSync(path.join(dir, "apps", "web"), { recursive: true });
    mkdirSync(path.join(dir, "infra", "docker"), { recursive: true });
    dirs.push(dir);
    return dir;
  }

  function modeOf(filePath: string): number {
    return statSync(filePath).mode & 0o777;
  }

  it("creates apps/api/.env owner-only on first write", () => {
    const repo = makeRepo();

    writeEnvFile(path.join(repo, "apps", "api"), { AGENT_SECRET: "abc123" });

    const envPath = path.join(repo, "apps", "api", ".env");
    expect(modeOf(envPath)).toBe(OWNER_ONLY);
    expect(readFileSync(envPath, "utf-8")).toContain("AGENT_SECRET=abc123");
  });

  it("tightens a pre-existing world-readable .env and its backup on rewrite", () => {
    const repo = makeRepo();
    const envPath = path.join(repo, "apps", "api", ".env");
    // Simulate an .env written by an older CLI with default (0644) perms.
    writeFileSync(envPath, "AGENT_SECRET=keep-me\n");
    chmodSync(envPath, 0o644);

    writeEnvFile(path.join(repo, "apps", "api"), {
      AGENT_SECRET: "new-secret",
    });

    expect(modeOf(envPath)).toBe(OWNER_ONLY);
    // The backup holds the previous generation of secrets — same bar.
    expect(modeOf(`${envPath}.bak`)).toBe(OWNER_ONLY);
    expect(readFileSync(`${envPath}.bak`, "utf-8")).toContain(
      "AGENT_SECRET=keep-me",
    );
  });

  it("creates apps/web/.env.local owner-only and tightens it on rewrite", () => {
    const repo = makeRepo();
    const webEnvPath = path.join(repo, "apps", "web", ".env.local");

    writeWebEnvFile(repo, "selfhost");
    expect(modeOf(webEnvPath)).toBe(OWNER_ONLY);

    writeFileSync(webEnvPath, "NEXT_PUBLIC_API_BASE_URL=http://stale\n");
    chmodSync(webEnvPath, 0o644);
    writeWebEnvFile(repo, "selfhost");
    expect(modeOf(webEnvPath)).toBe(OWNER_ONLY);
    expect(modeOf(`${webEnvPath}.bak`)).toBe(OWNER_ONLY);
  });

  it("creates infra/docker/.env owner-only on first write", () => {
    const repo = makeRepo();

    writeDockerComposeEnv(repo, { 5432: 5433 }, "selfhost");

    const composeEnvPath = path.join(repo, "infra", "docker", ".env");
    expect(modeOf(composeEnvPath)).toBe(OWNER_ONLY);
    expect(readFileSync(composeEnvPath, "utf-8")).toContain(
      "POSTGRES_HOST_PORT=5433",
    );
  });

  it("tightens infra/docker/.env and its backup on rewrite", () => {
    const repo = makeRepo();
    const composeEnvPath = path.join(repo, "infra", "docker", ".env");
    writeDockerComposeEnv(repo, {}, undefined);

    writeDockerComposeEnv(repo, { 3000: 3001 }, "selfhost");

    expect(modeOf(composeEnvPath)).toBe(OWNER_ONLY);
    expect(modeOf(`${composeEnvPath}.bak`)).toBe(OWNER_ONLY);
  });
});

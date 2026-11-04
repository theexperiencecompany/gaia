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
  readDockerComposePortOverrides,
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
    mkdirSync(path.join(dir, "packages", "cli", "selfhost"), {
      recursive: true,
    });
    dirs.push(dir);
    return dir;
  }

  function modeOf(filePath: string): number {
    return statSync(filePath).mode & 0o777;
  }

  it("creates apps/api/ in an install of setup files, which ships no apps/ directory", () => {
    const install = mkdtempSync(path.join(tmpdir(), "gaia-env-writer-"));
    dirs.push(install);

    writeEnvFile(path.join(install, "apps", "api"), { AGENT_SECRET: "abc" });

    const envPath = path.join(install, "apps", "api", ".env");
    expect(readFileSync(envPath, "utf-8")).toContain("AGENT_SECRET=abc");
    expect(modeOf(envPath)).toBe(OWNER_ONLY);
  });

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

  it("creates the compose env file owner-only on first write", () => {
    const repo = makeRepo();

    writeDockerComposeEnv(repo, { 5432: 5433 }, "selfhost");

    const composeEnvPath = path.join(
      repo,
      "packages",
      "cli",
      "selfhost",
      ".env",
    );
    expect(modeOf(composeEnvPath)).toBe(OWNER_ONLY);
    expect(readFileSync(composeEnvPath, "utf-8")).toContain(
      "POSTGRES_HOST_PORT=5433",
    );
  });

  it("tightens the compose env file and its backup on rewrite", () => {
    const repo = makeRepo();
    const composeEnvPath = path.join(
      repo,
      "packages",
      "cli",
      "selfhost",
      ".env",
    );
    writeDockerComposeEnv(repo, {}, undefined);

    writeDockerComposeEnv(repo, { 3000: 3001 }, "selfhost");

    expect(modeOf(composeEnvPath)).toBe(OWNER_ONLY);
    expect(modeOf(`${composeEnvPath}.bak`)).toBe(OWNER_ONLY);
  });
  it("tells Caddy to issue a local certificate for a domain no public CA certifies", () => {
    const repo = makeRepo();
    const composeEnvPath = path.join(
      repo,
      "packages",
      "cli",
      "selfhost",
      ".env",
    );

    writeDockerComposeEnv(repo, {}, "selfhost", {
      dockerSocketGid: 999,
      domain: "gaia.test",
    });
    expect(readFileSync(composeEnvPath, "utf-8")).toContain(
      "GAIA_CADDY_GLOBAL_OPTIONS=local_certs",
    );

    writeDockerComposeEnv(repo, {}, "selfhost", {
      dockerSocketGid: 999,
      domain: "gaia.example.com",
    });
    const publicEnv = readFileSync(composeEnvPath, "utf-8");
    expect(publicEnv).toContain("GAIA_DOMAIN=gaia.example.com");
    expect(publicEnv).not.toContain("GAIA_CADDY_GLOBAL_OPTIONS");
  });
});

describe("the compose env file each install reads", () => {
  const dirs: string[] = [];

  afterEach(() => {
    for (const dir of dirs.splice(0)) {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  function install(files: Record<string, string>): string {
    const dir = mkdtempSync(path.join(tmpdir(), "gaia-compose-env-"));
    dirs.push(dir);
    for (const [file, contents] of Object.entries(files)) {
      mkdirSync(path.dirname(path.join(dir, file)), { recursive: true });
      writeFileSync(path.join(dir, file), contents);
    }
    return dir;
  }

  it("reads a self-host install's ports from beside its compose files", () => {
    const root = install({
      "apps/api/.env": "SETUP_MODE=selfhost\n",
      "packages/cli/selfhost/docker-compose.selfhost.yml": "",
      "packages/cli/selfhost/.env": "WEB_HOST_PORT=3100\n",
    });
    expect(readDockerComposePortOverrides(root)).toEqual({ 3000: 3100 });
  });

  it("reads an install not yet moved by gaia update from infra/docker", () => {
    const root = install({
      "apps/api/.env": "SETUP_MODE=selfhost\n",
      "infra/docker/docker-compose.selfhost.yml": "",
      "infra/docker/.env": "WEB_HOST_PORT=3100\n",
    });
    expect(readDockerComposePortOverrides(root)).toEqual({ 3000: 3100 });
  });

  it("keeps a developer checkout's ports beside the developer stack", () => {
    const root = install({
      "apps/api/.env": "SETUP_MODE=developer\n",
      "packages/cli/selfhost/docker-compose.selfhost.yml": "",
      "infra/docker/.env": "WEB_HOST_PORT=3100\n",
    });
    expect(readDockerComposePortOverrides(root)).toEqual({ 3000: 3100 });
  });
});

describe("the compose env file a developer setup keeps", () => {
  const dirs: string[] = [];

  afterEach(() => {
    for (const dir of dirs.splice(0)) {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  function checkout(files: Record<string, string>): string {
    const dir = mkdtempSync(path.join(tmpdir(), "gaia-dev-env-"));
    dirs.push(dir);
    for (const [file, contents] of Object.entries(files)) {
      mkdirSync(path.dirname(path.join(dir, file)), { recursive: true });
      writeFileSync(path.join(dir, file), contents);
    }
    return dir;
  }

  it("reads it when apps/api/.env names no mode (an Atlas MONGO_DB)", () => {
    const root = checkout({
      "apps/api/.env": "MONGO_DB=mongodb+srv://cluster.example.net/gaia\n",
      "packages/cli/selfhost/docker-compose.selfhost.yml": "",
      "infra/docker/.env": "POSTGRES_HOST_PORT=5433\n",
    });
    expect(readDockerComposePortOverrides(root)).toEqual({ 5432: 5433 });
  });

  it("writes a developer's ports beside the developer stack", () => {
    const root = checkout({
      "packages/cli/selfhost/docker-compose.selfhost.yml": "",
      "infra/docker/docker-compose.yml": "",
    });
    writeDockerComposeEnv(root, { 5432: 5433 }, "developer");
    expect(
      readFileSync(path.join(root, "infra", "docker", ".env"), "utf-8"),
    ).toMatch(/^POSTGRES_HOST_PORT=5433$/m);
  });
});

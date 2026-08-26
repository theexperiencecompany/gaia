import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { runEnvSetup } from "../../src/lib/env-setup.js";
import { parseAssignedEnvKeys } from "../../src/lib/machine-secrets.js";
import { type CLIStore, createStore } from "../../src/ui/store.js";

/** Headless store: answers every pipeline prompt so runEnvSetup never blocks. */
function makeHeadlessStore(): CLIStore {
  const store = createStore();
  store.pushAnswerResolver((id) => {
    switch (id) {
      case "env_method":
        return "manual";
      case "env_alternatives":
        return { selectedGroups: [], values: {} };
      case "env_group":
        return {};
      case "env_var":
      case "setup_mode":
        return "";
      default:
        return undefined;
    }
  });
  return store;
}

describe("runEnvSetup env policy", () => {
  const dirs: string[] = [];

  afterEach(() => {
    for (const dir of dirs.splice(0)) {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  function makeRepo(): string {
    const dir = mkdtempSync(path.join(tmpdir(), "gaia-env-setup-"));
    // Mirror a real clone's layout: the writers expect these directories to
    // exist (a fresh clone always has them).
    mkdirSync(path.join(dir, "apps", "api"), { recursive: true });
    mkdirSync(path.join(dir, "apps", "web"), { recursive: true });
    mkdirSync(path.join(dir, "infra", "docker"), { recursive: true });
    dirs.push(dir);
    return dir;
  }

  function readApiEnv(repo: string): string {
    return readFileSync(path.join(repo, "apps", "api", ".env"), "utf-8");
  }

  it("selfhost mode writes ENV=selfhost + AUTH_MODE=local + machine secrets", async () => {
    const repo = makeRepo();
    const store = makeHeadlessStore();

    await runEnvSetup(store, repo, "selfhost");

    const content = readApiEnv(repo);
    const keys = parseAssignedEnvKeys(content);

    expect(content).toMatch(/^ENV=selfhost$/m);
    expect(content).toMatch(/^AUTH_MODE=local$/m);

    // All three machine secrets generated and hex-formatted.
    for (const name of [
      "AGENT_SECRET",
      "BOT_SESSION_TOKEN_SECRET",
      "EMAIL_UNSUBSCRIBE_SECRET",
    ]) {
      expect(keys.has(name)).toBe(true);
      expect(content).toMatch(new RegExp(`^${name}=[0-9a-f]{64}$`, "m"));
    }

    // Infra defaults applied for selfhost.
    expect(content).toMatch(/^MONGO_DB=mongodb:\/\/mongo:27017\/gaia$/m);
  });

  it("developer mode keeps ENV=development without AUTH_MODE", async () => {
    const repo = makeRepo();
    const store = makeHeadlessStore();

    await runEnvSetup(store, repo, "developer");

    const content = readApiEnv(repo);
    expect(content).toMatch(/^ENV=development$/m);
    expect(content).not.toMatch(/^AUTH_MODE=/m);
    // Developer infra defaults.
    expect(content).toMatch(/^MONGO_DB=mongodb:\/\/localhost:27017\/gaia$/m);
  });

  it("merge-don't-clobber: pre-existing secrets survive a rerun", async () => {
    const repo = makeRepo();
    const firstRunEnv = path.join(repo, "apps", "api", ".env");
    const preExisting = [
      "# GAIA Environment Configuration",
      "AGENT_SECRET=keep-me-untouched",
      "",
    ].join("\n");

    // Simulate an existing install: write the secret before setup runs.
    writeFileSync(firstRunEnv, preExisting);

    const store = makeHeadlessStore();
    await runEnvSetup(store, repo, "selfhost");

    const content = readApiEnv(repo);
    expect(content).toMatch(/^AGENT_SECRET=keep-me-untouched$/m);
    // The other two are freshly generated.
    expect(content).toMatch(/^BOT_SESSION_TOKEN_SECRET=[0-9a-f]{64}$/m);
    expect(content).toMatch(/^EMAIL_UNSUBSCRIBE_SECRET=[0-9a-f]{64}$/m);

    // A .bak backup of the previous file exists (writer behavior).
    const backup = readFileSync(`${firstRunEnv}.bak`, "utf-8");
    expect(backup).toContain("keep-me-untouched");
  });

  it("secrets are stable across two consecutive selfhost runs on the same repo", async () => {
    const repo = makeRepo();
    const extract = (content: string, name: string): string | undefined =>
      content.match(new RegExp(`^${name}=([0-9a-f]{64})$`, "m"))?.[1];

    await runEnvSetup(makeHeadlessStore(), repo, "selfhost");
    const firstContent = readApiEnv(repo);

    await runEnvSetup(makeHeadlessStore(), repo, "selfhost");
    const secondContent = readApiEnv(repo);

    for (const name of [
      "AGENT_SECRET",
      "BOT_SESSION_TOKEN_SECRET",
      "EMAIL_UNSUBSCRIBE_SECRET",
    ]) {
      const generated = extract(firstContent, name);
      expect(generated).toBeDefined();
      expect(extract(secondContent, name)).toBe(generated);
    }
  });

  it("writes NEXT_PUBLIC_APP_URL into the compose .env for selfhost", async () => {
    const repo = makeRepo();
    await runEnvSetup(makeHeadlessStore(), repo, "selfhost", { 3000: 4000 });

    const composeEnv = readFileSync(
      path.join(repo, "infra", "docker", ".env"),
      "utf-8",
    );
    expect(composeEnv).toMatch(
      /^NEXT_PUBLIC_APP_URL=http:\/\/localhost:4000$/m,
    );
    expect(composeEnv).toMatch(/^WEB_HOST_PORT=4000$/m);
  });
});

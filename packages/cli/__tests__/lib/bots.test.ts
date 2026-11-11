import {
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
  BOT_ENV_KEYS,
  botComposeFile,
  botContainerState,
  SELFHOST_BOTS,
  updateApiEnv,
  writeBotsEnv,
} from "../../src/lib/bots.js";
import { parseEnvFileValues } from "../../src/lib/env-writer.js";

const API_ENV = [
  "SETUP_MODE=selfhost",
  "FRONTEND_URL=https://gaia.example.com",
  "RABBITMQ_URL=amqp://guest:guest@rabbitmq:5672/", // pragma: allowlist secret
  "GAIA_BOT_API_KEY=bot-api-key",
  "AGENT_SECRET=a",
  "BOT_SESSION_TOKEN_SECRET=b",
  "EMAIL_UNSUBSCRIBE_SECRET=c",
  "SHARE_GRANT_SECRET=d",
].join("\n");

const dirs: string[] = [];

afterEach(() => {
  for (const dir of dirs.splice(0))
    rmSync(dir, { recursive: true, force: true });
});

function makeRepo(apiEnv: string = API_ENV): string {
  const dir = mkdtempSync(path.join(tmpdir(), "gaia-bots-"));
  mkdirSync(path.join(dir, "apps", "api"), { recursive: true });
  mkdirSync(path.join(dir, "apps", "bots"), { recursive: true });
  writeFileSync(path.join(dir, "apps", "api", ".env"), apiEnv);
  dirs.push(dir);
  return dir;
}

function readEnv(repo: string, app: "api" | "bots"): Record<string, string> {
  return parseEnvFileValues(
    readFileSync(path.join(repo, "apps", app, ".env"), "utf-8"),
  );
}

describe("writeBotsEnv", () => {
  it("copies the bot key, public URL and broker from apps/api/.env", () => {
    const repo = makeRepo();

    writeBotsEnv(repo, { set: { TELEGRAM_BOT_TOKEN: "123:abc" } });

    expect(readEnv(repo, "bots")).toMatchObject({
      TELEGRAM_BOT_TOKEN: "123:abc",
      GAIA_BOT_API_KEY: "bot-api-key",
      GAIA_FRONTEND_URL: "https://gaia.example.com",
      RABBITMQ_URL: "amqp://guest:guest@rabbitmq:5672/", // pragma: allowlist secret
    });
  });

  it("is owner-only: it holds platform tokens", () => {
    const repo = makeRepo();

    writeBotsEnv(repo);

    const mode = statSync(path.join(repo, "apps", "bots", ".env")).mode;
    expect(mode & 0o777).toBe(0o600);
  });

  it("generates the log-hash secret once and keeps it", () => {
    const repo = makeRepo();

    writeBotsEnv(repo);
    const first = readEnv(repo, "bots").BOT_LOG_HASH_SECRET;
    writeBotsEnv(repo);

    expect(first).toMatch(/^[0-9a-f]{64}$/);
    expect(readEnv(repo, "bots").BOT_LOG_HASH_SECRET).toBe(first);
  });

  it("follows a changed domain on the next write", () => {
    const repo = makeRepo();
    writeBotsEnv(repo);

    updateApiEnv(repo, { set: { FRONTEND_URL: "https://new.example.com" } });
    writeBotsEnv(repo);

    expect(readEnv(repo, "bots").GAIA_FRONTEND_URL).toBe(
      "https://new.example.com",
    );
  });

  it("gives an install from before the bots one bot key, shared with the API", () => {
    const repo = makeRepo(
      API_ENV.replace("GAIA_BOT_API_KEY=bot-api-key\n", ""),
    );

    writeBotsEnv(repo);

    const apiKey = readEnv(repo, "api").GAIA_BOT_API_KEY;
    expect(apiKey).toMatch(/^[0-9a-f]{64}$/);
    expect(readEnv(repo, "bots").GAIA_BOT_API_KEY).toBe(apiKey);
    expect(readEnv(repo, "api")).not.toHaveProperty("INSTANCE_SECRET");
  });

  it("deletes exactly the removed bot's keys", () => {
    const repo = makeRepo();
    writeBotsEnv(repo, {
      set: {
        TELEGRAM_BOT_TOKEN: "t",
        DISCORD_BOT_TOKEN: "d",
        DISCORD_CLIENT_ID: "1",
      },
    });

    writeBotsEnv(repo, { unset: BOT_ENV_KEYS.discord });

    const env = readEnv(repo, "bots");
    expect(env.TELEGRAM_BOT_TOKEN).toBe("t");
    expect(env).not.toHaveProperty("DISCORD_BOT_TOKEN");
    expect(env).not.toHaveProperty("DISCORD_CLIENT_ID");
  });

  it("refuses an install whose apps/api/.env has no public URL", () => {
    const repo = makeRepo(
      API_ENV.replace("FRONTEND_URL=https://gaia.example.com\n", ""),
    );

    expect(() => writeBotsEnv(repo)).toThrow("FRONTEND_URL is not set");
  });
});

describe("botComposeFile", () => {
  it("names a file that exists in the self-host folder for every bot", () => {
    const dockerDir = path.resolve(__dirname, "../../selfhost");
    for (const bot of SELFHOST_BOTS) {
      expect(() =>
        statSync(path.join(dockerDir, botComposeFile(bot))),
      ).not.toThrow();
    }
  });
});

describe("botContainerState", () => {
  it("is healthy only once the healthcheck passes", () => {
    expect(
      botContainerState("slack", [
        { service: "bot-slack", state: "running", health: "healthy" },
      ]),
    ).toEqual({ health: "healthy", detail: "running, healthy" });
    expect(
      botContainerState("slack", [
        { service: "bot-slack", state: "running", health: "health: starting" },
      ]).health,
    ).toBe("starting");
  });

  it("fails a restarting, unhealthy or missing bot, never another bot's container", () => {
    expect(
      botContainerState("slack", [
        { service: "bot-slack", state: "restarting" },
      ]).health,
    ).toBe("failing");
    expect(
      botContainerState("slack", [
        { service: "bot-slack", state: "running", health: "unhealthy" },
      ]).health,
    ).toBe("failing");
    expect(
      botContainerState("slack", [
        { service: "bot-telegram", state: "running", health: "healthy" },
      ]),
    ).toEqual({ health: "failing", detail: "not created" });
  });
});

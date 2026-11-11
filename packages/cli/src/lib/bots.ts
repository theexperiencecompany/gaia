/**
 * The chat bots a self-host install can run, and the env file they read.
 *
 * Each enabled bot is one compose override (packages/cli/selfhost/docker-compose.bot-<bot>.yml)
 * and one entry in the CLI config. apps/bots/.env holds the platform tokens,
 * the log-hash secret generated once, and the values a bot needs from
 * apps/api/.env, which are copied again on every start so a changed domain or
 * a restored apps/api/.env can never leave the bots on stale values.
 * @module lib/bots
 */

import * as fs from "node:fs";
import * as path from "node:path";
import type { ComposeContainerInfo } from "./docker.js";
import { parseEnvFileValues, writeEnvFile } from "./env-writer.js";
import {
  collectMachineSecrets,
  generateMachineSecret,
} from "./machine-secrets.js";

export const SELFHOST_BOTS = ["telegram", "discord", "slack"] as const;

export type SelfhostBot = (typeof SELFHOST_BOTS)[number];

/** The apps/bots/.env keys each bot owns; `gaia bots remove` deletes exactly these. */
export const BOT_ENV_KEYS: Record<SelfhostBot, readonly string[]> = {
  telegram: ["TELEGRAM_BOT_TOKEN"],
  discord: ["DISCORD_BOT_TOKEN", "DISCORD_CLIENT_ID"],
  slack: ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_SIGNING_SECRET"],
};

/**
 * The apps/api/.env keys naming each bot to the web app (GET /setup/status);
 * `gaia bots add` sets them, `gaia bots remove` deletes exactly these.
 */
export const BOT_API_ENV_KEYS = {
  telegram: "TELEGRAM_BOT_USERNAME",
  discord: "DISCORD_CLIENT_ID",
  slack: "SLACK_WORKSPACE_URL",
} as const satisfies Record<SelfhostBot, string>;

/** apps/bots/.env key → the apps/api/.env key it is copied from. */
const BOT_ENV_FROM_API_ENV = {
  GAIA_BOT_API_KEY: "GAIA_BOT_API_KEY",
  GAIA_FRONTEND_URL: "FRONTEND_URL",
  RABBITMQ_URL: "RABBITMQ_URL",
} as const;

/** HMAC key the bots hash platform user ids with before logging them. */
const BOT_LOG_HASH_SECRET_KEY = "BOT_LOG_HASH_SECRET";

/** The compose service a bot runs as. */
export function botService(bot: SelfhostBot): string {
  return `bot-${bot}`;
}

/** Where a bot's container stands: serving, still connecting, or broken / absent. */
type BotHealth = "healthy" | "starting" | "failing";

export interface BotContainerState {
  health: BotHealth;
  /** Docker's own words, e.g. "running, healthy" or "not created". */
  detail: string;
}

/** Judge a bot's container; its healthcheck passes only once the platform connection is up. */
export function botContainerState(
  bot: SelfhostBot,
  containers: readonly ComposeContainerInfo[],
): BotContainerState {
  const container = containers.find((c) => c.service === botService(bot));
  if (!container) return { health: "failing", detail: "not created" };
  const detail = [container.state, container.health].filter(Boolean).join(", ");
  if (container.state !== "running" || container.health === "unhealthy") {
    return { health: "failing", detail };
  }
  const healthy =
    container.health === undefined || container.health === "healthy";
  return { health: healthy ? "healthy" : "starting", detail };
}

/** The compose override (in the self-host folder) that adds a bot to the stack. */
export function botComposeFile(bot: SelfhostBot): string {
  return `docker-compose.${botService(bot)}.yml`;
}

function apiEnvDir(repoPath: string): string {
  return path.join(repoPath, "apps", "api");
}

function botsEnvDir(repoPath: string): string {
  return path.join(repoPath, "apps", "bots");
}

function readEnvValues(dir: string): Record<string, string> {
  const envPath = path.join(dir, ".env");
  return fs.existsSync(envPath)
    ? parseEnvFileValues(fs.readFileSync(envPath, "utf-8"))
    : {};
}

/** A change to one env file: keys to set, then keys to delete. */
export interface EnvChange {
  set?: Record<string, string>;
  unset?: readonly string[];
}

function applyEnvChange(
  values: Record<string, string>,
  change: EnvChange,
): Record<string, string> {
  const next = { ...values, ...change.set };
  for (const key of change.unset ?? []) delete next[key];
  return next;
}

/** Apply a change to apps/api/.env, rewriting it only when a value differs. */
export function updateApiEnv(repoPath: string, change: EnvChange): void {
  const dir = apiEnvDir(repoPath);
  const current = readEnvValues(dir);
  const next = applyEnvChange(current, change);
  if (JSON.stringify(next) !== JSON.stringify(current)) {
    writeEnvFile(dir, next);
  }
}

/**
 * Rewrite apps/bots/.env (0600) from its current values, this change, and the
 * values copied from apps/api/.env. An install from before the bots generates
 * the bot key into apps/api/.env here, the same way `gaia up` does.
 * @throws Error when apps/api/.env is missing or has no FRONTEND_URL or RABBITMQ_URL.
 */
export function writeBotsEnv(repoPath: string, change: EnvChange = {}): void {
  const apiEnvPath = path.join(apiEnvDir(repoPath), ".env");
  if (!fs.existsSync(apiEnvPath)) {
    throw new Error(
      `${apiEnvPath} does not exist; run 'gaia up' to configure the install first.`,
    );
  }
  const missingSecrets = collectMachineSecrets(
    fs.readFileSync(apiEnvPath, "utf-8"),
  );
  if (Object.keys(missingSecrets).length > 0) {
    updateApiEnv(repoPath, { set: missingSecrets });
  }
  const apiEnv = readEnvValues(apiEnvDir(repoPath));

  const copied: Record<string, string> = {};
  for (const [botKey, apiKey] of Object.entries(BOT_ENV_FROM_API_ENV)) {
    const value = apiEnv[apiKey];
    if (!value) {
      throw new Error(
        `${apiKey} is not set in apps/api/.env; run 'gaia up' to configure the install first.`,
      );
    }
    copied[botKey] = value;
  }

  const dir = botsEnvDir(repoPath);
  const values = applyEnvChange(readEnvValues(dir), change);
  values[BOT_LOG_HASH_SECRET_KEY] ??= generateMachineSecret();
  writeEnvFile(dir, { ...values, ...copied });
}

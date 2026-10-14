/**
 * `gaia bots add|list|remove` — run GAIA's chat bots on a self-host install
 * with the operator's own bot tokens. Plain-text output, like doctor.
 * @module commands/bots/handler
 */

import {
  discordInviteUrl,
  verifyDiscordToken,
  verifySlackTokens,
  verifyTelegramToken,
} from "../../lib/bot-tokens.js";
import {
  BOT_ENV_KEYS,
  botService,
  type EnvChange,
  type SelfhostBot,
  updateApiEnv,
  writeBotsEnv,
} from "../../lib/bots.js";
import { readConfig, updateConfig } from "../../lib/config.js";
import {
  COMPOSE_PROJECT_BY_MODE,
  getComposeProjectContainers,
} from "../../lib/docker.js";
import { readDockerComposePortOverrides } from "../../lib/env-writer.js";
import {
  detectSetupMode,
  findInstallRoot,
  runSelfhostOneOff,
  startServices,
} from "../../lib/service-starter.js";

/** Where the API reads the Telegram bot behind onboarding's one-tap link. */
const TELEGRAM_BOT_USERNAME_KEY = "TELEGRAM_BOT_USERNAME";

/** Registers the bot's commands with its platform, from inside its image. */
const COMMAND_REGISTRATION: Partial<Record<SelfhostBot, string[]>> = {
  discord: ["node", "dist/deploy-commands.js"],
  telegram: ["node", "dist/set-commands.js"],
};

export interface BotCredentials {
  token?: string;
  appToken?: string;
  signingSecret?: string;
}

function out(line = ""): void {
  process.stdout.write(`${line}\n`);
}

function requireOption(value: string | undefined, flag: string): string {
  if (!value) throw new Error(`Missing ${flag}.`);
  return value;
}

/** The self-host install to change; bots run only alongside its compose stack. */
async function requireSelfhostInstall(): Promise<string> {
  const repoPath = findInstallRoot();
  if (!repoPath || (await detectSetupMode(repoPath)) !== "selfhost") {
    throw new Error(
      "No self-host GAIA install found. Run 'gaia up' first; chat bots run alongside it.",
    );
  }
  return repoPath;
}

interface VerifiedBot {
  botsEnv: Record<string, string>;
  apiEnv?: EnvChange;
  nextSteps: string[];
}

async function verifyCredentials(
  bot: SelfhostBot,
  credentials: BotCredentials,
): Promise<VerifiedBot> {
  const token = requireOption(credentials.token, "--token");
  if (bot === "telegram") {
    const username = await verifyTelegramToken(token);
    return {
      botsEnv: { TELEGRAM_BOT_TOKEN: token },
      apiEnv: { set: { [TELEGRAM_BOT_USERNAME_KEY]: username } },
      nextSteps: [
        `Open https://t.me/${username} and send /auth to link your GAIA account.`,
      ],
    };
  }
  if (bot === "discord") {
    const applicationId = await verifyDiscordToken(token);
    return {
      botsEnv: { DISCORD_BOT_TOKEN: token, DISCORD_CLIENT_ID: applicationId },
      nextSteps: [
        `Add the bot to a server: ${discordInviteUrl(applicationId)}`,
        "Then run /auth in Discord to link your GAIA account.",
      ],
    };
  }
  const appToken = requireOption(credentials.appToken, "--app-token");
  const signingSecret = requireOption(
    credentials.signingSecret,
    "--signing-secret",
  );
  const team = await verifySlackTokens(token, appToken);
  return {
    botsEnv: {
      SLACK_BOT_TOKEN: token,
      SLACK_APP_TOKEN: appToken,
      SLACK_SIGNING_SECRET: signingSecret,
    },
    nextSteps: [
      `Running in the ${team} workspace. Run /auth in Slack to link your GAIA account.`,
    ],
  };
}

/** Recreate the stack with the saved bot set; removed bots stop as orphans. */
async function restartStack(repoPath: string): Promise<void> {
  await startServices(
    repoPath,
    "selfhost",
    (status) => out(status),
    readDockerComposePortOverrides(repoPath),
    undefined,
    { pull: "missing" },
  );
}

export async function runBotsAdd(
  bot: SelfhostBot,
  credentials: BotCredentials,
): Promise<void> {
  const repoPath = await requireSelfhostInstall();
  out(`Checking the ${bot} credentials...`);
  const verified = await verifyCredentials(bot, credentials);

  writeBotsEnv(repoPath, { set: verified.botsEnv });
  if (verified.apiEnv) updateApiEnv(repoPath, verified.apiEnv);
  const enabled = readConfig()?.bots ?? [];
  if (!enabled.includes(bot)) updateConfig({ bots: [...enabled, bot] });

  await restartStack(repoPath);
  const registration = COMMAND_REGISTRATION[bot];
  if (registration) {
    out(`Registering the ${bot} bot's commands...`);
    await runSelfhostOneOff(repoPath, botService(bot), registration);
  }

  out(`The ${bot} bot is running.`);
  for (const step of verified.nextSteps) out(step);
}

export async function runBotsRemove(bot: SelfhostBot): Promise<void> {
  const repoPath = await requireSelfhostInstall();
  const enabled = readConfig()?.bots ?? [];
  if (!enabled.includes(bot)) {
    throw new Error(`The ${bot} bot is not enabled. See 'gaia bots list'.`);
  }

  updateConfig({ bots: enabled.filter((b) => b !== bot) });
  writeBotsEnv(repoPath, { unset: BOT_ENV_KEYS[bot] });
  if (bot === "telegram") {
    updateApiEnv(repoPath, { unset: [TELEGRAM_BOT_USERNAME_KEY] });
  }
  await restartStack(repoPath);
  out(`The ${bot} bot is stopped and its credentials are deleted.`);
}

export async function runBotsList(): Promise<void> {
  await requireSelfhostInstall();
  const enabled = readConfig()?.bots ?? [];
  if (enabled.length === 0) {
    out(
      "No chat bots enabled. Add one with: gaia bots add <telegram|discord|slack> --token <token>",
    );
    return;
  }
  const containers = await getComposeProjectContainers(
    COMPOSE_PROJECT_BY_MODE.selfhost,
  );
  for (const bot of enabled) {
    const container = containers.find((c) => c.service === botService(bot));
    const state = container
      ? [container.state, container.health].filter(Boolean).join(", ")
      : "not created";
    out(`  ${bot.padEnd(10)}${state}`);
  }
}

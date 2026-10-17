/**
 * `gaia bots add|list|remove` — run GAIA's chat bots on a self-host install
 * with the operator's own bot tokens. Plain-text output, like doctor.
 * @module commands/bots/handler
 */

import {
  discordInviteUrl,
  telegramBotUrl,
} from "../../../../../libs/shared/ts/src/utils/botLinks.js";
import {
  verifyDiscordToken,
  verifySlackTokens,
  verifyTelegramToken,
} from "../../lib/bot-tokens.js";
import {
  BOT_API_ENV_KEYS,
  BOT_ENV_KEYS,
  botContainerState,
  botService,
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
import { delay } from "../../lib/flow-utils.js";
import { isInteractive } from "../../lib/non-tty.js";
import { askSecret } from "../../lib/prompt.js";
import {
  detectSetupMode,
  findInstallRoot,
  runSelfhostOneOff,
  startServices,
} from "../../lib/service-starter.js";
import { wrapForTerminal } from "../../lib/terminal-text.js";
import { MARK } from "../../ui/constants.js";

/** Registers the bot's commands with its platform, from inside its image. */
const COMMAND_REGISTRATION: Partial<Record<SelfhostBot, string[]>> = {
  discord: ["node", "dist/deploy-commands.js"],
  telegram: ["node", "dist/set-commands.js"],
};

/** The bot healthcheck runs every 30s, so a healthy bot shows within ~30s of starting. */
const BOT_START_TIMEOUT_MS = 120_000;
const BOT_POLL_INTERVAL_MS = 3_000;

export interface BotCredentials {
  token?: string;
  appToken?: string;
  signingSecret?: string;
}

interface CredentialPrompt {
  key: keyof BotCredentials;
  flag: string;
  label: string;
  /** Where to find the value, shown before prompting for it. */
  hint: string;
}

const CREDENTIAL_PROMPTS: Record<SelfhostBot, readonly CredentialPrompt[]> = {
  telegram: [
    {
      key: "token",
      flag: "--token",
      label: "Telegram bot token",
      hint: "In Telegram, message @BotFather, send /newbot and copy the token it replies with.",
    },
  ],
  discord: [
    {
      key: "token",
      flag: "--token",
      label: "Discord bot token",
      hint: "At https://discord.com/developers/applications open your app > Bot > Reset Token. Turn on Message Content Intent on the same page.",
    },
  ],
  slack: [
    {
      key: "token",
      flag: "--token",
      label: "Slack bot token (xoxb-)",
      hint: "At https://api.slack.com/apps open your app > OAuth & Permissions > Bot User OAuth Token.",
    },
    {
      key: "appToken",
      flag: "--app-token",
      label: "Slack app-level token (xapp-)",
      hint: "Turn on Socket Mode, then Basic Information > App-Level Tokens: create one with the connections:write scope.",
    },
    {
      key: "signingSecret",
      flag: "--signing-secret",
      label: "Slack signing secret",
      hint: "Basic Information > App Credentials > Signing Secret.",
    },
  ],
};

function out(line = ""): void {
  process.stdout.write(`${line}\n`);
}

function requireOption(value: string | undefined, flag: string): string {
  if (!value) throw new Error(`Missing ${flag}.`);
  return value;
}

/** How the bots are named in copy. */
const BOT_NAMES: Record<SelfhostBot, string> = {
  telegram: "Telegram",
  discord: "Discord",
  slack: "Slack",
};

/** Tries a person gets at pasting credentials the platform accepts. */
const CREDENTIAL_ATTEMPTS = 3;

/** Fill each credential not passed as a flag by prompting, or name the flag when there is no terminal. */
async function resolveCredentials(
  bot: SelfhostBot,
  given: BotCredentials,
): Promise<BotCredentials> {
  const resolved: BotCredentials = { ...given };
  for (const prompt of CREDENTIAL_PROMPTS[bot]) {
    if (resolved[prompt.key]) continue;
    if (!isInteractive()) {
      throw new Error(`Missing ${prompt.flag}. ${prompt.hint}`);
    }
    out();
    out(wrapForTerminal(prompt.hint));
    const value = await askSecret(prompt.label);
    if (!value) throw new Error(`No ${prompt.label} entered. Nothing changed.`);
    resolved[prompt.key] = value;
  }
  return resolved;
}

/**
 * Check the credentials with the platform. A person who pasted them gets
 * another try (up to CREDENTIAL_ATTEMPTS) instead of retyping the command;
 * credentials from flags fail at once.
 */
async function verifiedCredentials(
  bot: SelfhostBot,
  given: BotCredentials,
): Promise<VerifiedBot> {
  for (let attempt = 1; ; attempt++) {
    const resolved = await resolveCredentials(bot, given);
    out(`Checking your ${BOT_NAMES[bot]} credentials…`);
    try {
      return await verifyCredentials(bot, resolved);
    } catch (error) {
      const prompted = CREDENTIAL_PROMPTS[bot].some((p) => !given[p.key]);
      const triesLeft = CREDENTIAL_ATTEMPTS - attempt;
      if (!prompted || !isInteractive() || triesLeft === 0) throw error;
      out(
        `${MARK.fail} ${(error as Error).message} Paste ${triesLeft === 1 ? "it" : "them"} again (${triesLeft} ${triesLeft === 1 ? "try" : "tries"} left), or press Esc to stop.`,
      );
    }
  }
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
  /** The bot's public handle, the value of its BOT_API_ENV_KEYS key. */
  handle: string;
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
      handle: username,
      nextSteps: [
        `Open ${telegramBotUrl(username)} and send /auth to link your GAIA account.`,
      ],
    };
  }
  if (bot === "discord") {
    const applicationId = await verifyDiscordToken(token);
    return {
      botsEnv: { DISCORD_BOT_TOKEN: token, DISCORD_CLIENT_ID: applicationId },
      handle: applicationId,
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
  const workspace = await verifySlackTokens(token, appToken);
  return {
    botsEnv: {
      SLACK_BOT_TOKEN: token,
      SLACK_APP_TOKEN: appToken,
      SLACK_SIGNING_SECRET: signingSecret,
    },
    handle: workspace.url,
    nextSteps: [
      `Running in the ${workspace.name} workspace. Run /auth in Slack to link your GAIA account.`,
    ],
  };
}

/** Poll the bot's container until its healthcheck passes, i.e. it is connected to its platform. */
async function waitForBotHealthy(bot: SelfhostBot): Promise<void> {
  const project = COMPOSE_PROJECT_BY_MODE.selfhost;
  const deadline = Date.now() + BOT_START_TIMEOUT_MS;
  for (;;) {
    const state = botContainerState(
      bot,
      await getComposeProjectContainers(project),
    );
    if (state.health === "healthy") return;
    if (Date.now() >= deadline) {
      throw new Error(
        `The ${BOT_NAMES[bot]} bot did not come up (${state.detail}). See why with 'docker compose -p ${project} logs ${botService(bot)}'; 'gaia bots remove ${bot}' undoes the setup.`,
      );
    }
    await delay(BOT_POLL_INTERVAL_MS);
  }
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
  const verified = await verifiedCredentials(bot, credentials);

  writeBotsEnv(repoPath, { set: verified.botsEnv });
  updateApiEnv(repoPath, { set: { [BOT_API_ENV_KEYS[bot]]: verified.handle } });
  const enabled = readConfig()?.bots ?? [];
  if (!enabled.includes(bot)) updateConfig({ bots: [...enabled, bot] });

  await restartStack(repoPath);
  const registration = COMMAND_REGISTRATION[bot];
  if (registration) {
    out(`Registering the ${BOT_NAMES[bot]} bot's commands…`);
    await runSelfhostOneOff(repoPath, botService(bot), registration);
  }

  out(`Waiting for the ${BOT_NAMES[bot]} bot to connect…`);
  await waitForBotHealthy(bot);
  out(`${MARK.ok} The ${BOT_NAMES[bot]} bot is running`);
  for (const step of verified.nextSteps) out(step);
}

export async function runBotsRemove(bot: SelfhostBot): Promise<void> {
  const repoPath = await requireSelfhostInstall();
  const enabled = readConfig()?.bots ?? [];
  if (!enabled.includes(bot)) {
    throw new Error(
      `The ${BOT_NAMES[bot]} bot is not enabled. See 'gaia bots list'.`,
    );
  }

  updateConfig({ bots: enabled.filter((b) => b !== bot) });
  writeBotsEnv(repoPath, { unset: BOT_ENV_KEYS[bot] });
  updateApiEnv(repoPath, { unset: [BOT_API_ENV_KEYS[bot]] });
  await restartStack(repoPath);
  out(
    `${MARK.ok} The ${BOT_NAMES[bot]} bot is stopped and its credentials are deleted`,
  );
}

export async function runBotsList(): Promise<void> {
  await requireSelfhostInstall();
  const enabled = readConfig()?.bots ?? [];
  if (enabled.length === 0) {
    out(
      "No chat bots enabled. Add one with: gaia bots add <telegram|discord|slack>",
    );
    return;
  }
  const containers = await getComposeProjectContainers(
    COMPOSE_PROJECT_BY_MODE.selfhost,
  );
  for (const bot of enabled) {
    out(`  ${bot.padEnd(10)}${botContainerState(bot, containers).detail}`);
  }
}

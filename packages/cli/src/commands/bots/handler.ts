/**
 * `gaia bots add|list|remove` — run GAIA's chat bots on a self-host install
 * with the operator's own bot tokens. add and remove are steps on the shared
 * run screen; list prints its rows.
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
import { type CommandEnding, setEnding } from "../../lib/command-ending.js";
import { runCommandUI } from "../../lib/command-runner.js";
import { readConfig, updateConfig } from "../../lib/config.js";
import { serviceName } from "../../lib/display-names.js";
import {
  COMPOSE_PROJECT_BY_MODE,
  getComposeProjectContainers,
} from "../../lib/docker.js";
import { readDockerComposePortOverrides } from "../../lib/env-writer.js";
import { delay } from "../../lib/flow-utils.js";
import { detectSetupMode, findInstallRoot } from "../../lib/install-root.js";
import { isInteractive } from "../../lib/non-tty.js";
import {
  finishStep,
  initSteps,
  startStep,
  updateStep,
} from "../../lib/run-steps.js";
import { runSelfhostOneOff } from "../../lib/service-starter.js";
import {
  imagesStep,
  START_STEP,
  startSelfhostServices,
} from "../../lib/start-steps.js";
import { MARK } from "../../ui/constants.js";
import { printHeader } from "../../ui/header/header-lines.js";
import type { CLIStore } from "../../ui/store.js";
import { BOT_CREDENTIAL_INPUT, type CredentialRequest } from "./prompt.js";

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

/**
 * Fill each credential not passed as a flag by asking on screen, or name the
 * flag when there is no terminal. Where to find each one is said on the first
 * try only; a retry says why the last paste was refused.
 */
async function resolveCredentials(
  store: CLIStore,
  bot: SelfhostBot,
  given: BotCredentials,
  retry?: string,
): Promise<BotCredentials> {
  const resolved: BotCredentials = { ...given };
  // One refusal note per round, above the first credential asked again.
  let note = retry;
  for (const prompt of CREDENTIAL_PROMPTS[bot]) {
    if (resolved[prompt.key]) continue;
    if (!isInteractive()) {
      throw new Error(`Missing ${prompt.flag}. ${prompt.hint}`);
    }
    const request: CredentialRequest = retry
      ? { label: prompt.label, ...(note ? { retry: note } : {}) }
      : { label: prompt.label, hint: prompt.hint };
    const value = await store.waitForInput(BOT_CREDENTIAL_INPUT, request);
    if (!value) throw new Error(`No ${prompt.label} entered. Nothing changed.`);
    resolved[prompt.key] = value;
    note = undefined;
  }
  return resolved;
}

/**
 * Check the credentials with the platform. A person who pasted them gets
 * another try (up to CREDENTIAL_ATTEMPTS) instead of retyping the command;
 * credentials from flags fail at once.
 */
async function verifiedCredentials(
  store: CLIStore,
  bot: SelfhostBot,
  given: BotCredentials,
): Promise<VerifiedBot> {
  let retry: string | undefined;
  for (let attempt = 1; ; attempt++) {
    const resolved = await resolveCredentials(store, bot, given, retry);
    startStep(store, "check");
    try {
      return await verifyCredentials(bot, resolved);
    } catch (error) {
      const pasted = CREDENTIAL_PROMPTS[bot].filter((p) => !given[p.key]);
      const triesLeft = CREDENTIAL_ATTEMPTS - attempt;
      if (pasted.length === 0 || !isInteractive() || triesLeft === 0) {
        throw error;
      }
      // Back to waiting on the next paste: the check has not run on it yet.
      updateStep(store, "check", { state: "pending" });
      retry = `${(error as Error).message} Paste ${pasted.length === 1 ? "it" : "them"} again (${triesLeft} ${triesLeft === 1 ? "try" : "tries"} left).`;
    }
  }
}

/** The self-host install to change; bots run only alongside its compose stack. */
async function requireSelfhostInstall(): Promise<string> {
  const repoPath = findInstallRoot();
  if (!repoPath || (await detectSetupMode(repoPath)) !== "selfhost") {
    throw new Error(
      "No self-host GAIA install found.\nInstall it with 'gaia up' first; chat bots run alongside it.",
    );
  }
  return repoPath;
}

interface VerifiedBot {
  botsEnv: Record<string, string>;
  /** The bot's public handle, the value of its BOT_API_ENV_KEYS key. */
  handle: string;
  next: CommandEnding;
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
      next: {
        lead: "Link your account:",
        target: telegramBotUrl(username),
        also: ["Open it and send /auth."],
      },
    };
  }
  if (bot === "discord") {
    const applicationId = await verifyDiscordToken(token);
    return {
      botsEnv: { DISCORD_BOT_TOKEN: token, DISCORD_CLIENT_ID: applicationId },
      handle: applicationId,
      next: {
        lead: "Add the bot to a server:",
        target: discordInviteUrl(applicationId),
        also: ["Then run /auth in Discord to link your GAIA account."],
      },
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
    next: {
      lead: "Link your account:",
      target: "/auth",
      also: [`Run it in Slack, in the ${workspace.name} workspace.`],
    },
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
        `The ${BOT_NAMES[bot]} bot did not come up (${state.detail}).\nSee why with 'docker compose -p ${project} logs ${botService(bot)}'; 'gaia bots remove ${bot}' undoes the setup.`,
      );
    }
    await delay(BOT_POLL_INTERVAL_MS);
  }
}

/** Recreate the stack with the saved bot set (a removed bot stops as an orphan); the restart is its two steps. */
async function restartStack(store: CLIStore, repoPath: string): Promise<void> {
  const started = await startSelfhostServices(
    store,
    repoPath,
    readDockerComposePortOverrides(repoPath),
    { pull: "missing" },
  );
  finishStep(
    store,
    START_STEP.id,
    started === 0 ? "GAIA was already running" : undefined,
  );
}

function restartSteps() {
  return [imagesStep(false), START_STEP];
}

export async function runBotsAdd(
  store: CLIStore,
  bot: SelfhostBot,
  credentials: BotCredentials,
): Promise<void> {
  const name = BOT_NAMES[bot];
  const registration = COMMAND_REGISTRATION[bot];
  initSteps(store, [
    {
      id: "check",
      label: `Checking your ${name} credentials`,
      doneLabel: `${name} accepted the credentials`,
    },
    {
      id: "save",
      label: "Saving the bot's settings",
      doneLabel: "Saved the bot's settings",
      minor: true,
    },
    ...restartSteps(),
    ...(registration
      ? [
          {
            id: "register",
            label: "Registering the bot's commands",
            doneLabel: "Registered the bot's commands",
          },
        ]
      : []),
    {
      id: "connect",
      label: `Waiting for the ${name} bot to connect`,
      doneLabel: `The ${serviceName(botService(bot))} is connected`,
    },
  ]);
  const repoPath = await requireSelfhostInstall();
  const verified = await verifiedCredentials(store, bot, credentials);
  finishStep(store, "check");

  startStep(store, "save");
  writeBotsEnv(repoPath, { set: verified.botsEnv });
  updateApiEnv(repoPath, { set: { [BOT_API_ENV_KEYS[bot]]: verified.handle } });
  const enabled = readConfig()?.bots ?? [];
  if (!enabled.includes(bot)) updateConfig({ bots: [...enabled, bot] });
  finishStep(store, "save");

  await restartStack(store, repoPath);
  if (registration) {
    startStep(store, "register");
    await runSelfhostOneOff(repoPath, botService(bot), registration);
    finishStep(store, "register");
  }

  startStep(store, "connect");
  await waitForBotHealthy(bot);
  finishStep(store, "connect");
  setEnding(store, verified.next);
}

export async function runBotsRemove(
  store: CLIStore,
  bot: SelfhostBot,
): Promise<void> {
  const name = BOT_NAMES[bot];
  initSteps(store, [
    {
      id: "forget",
      label: `Deleting the ${name} bot's credentials`,
      doneLabel: `Deleted the ${name} bot's credentials`,
      minor: true,
    },
    ...restartSteps(),
  ]);
  const repoPath = await requireSelfhostInstall();
  const enabled = readConfig()?.bots ?? [];
  if (!enabled.includes(bot)) {
    throw new Error(
      `The ${name} bot isn't set up, so there is nothing to remove.\n'gaia bots list' shows the ones that are.`,
    );
  }

  startStep(store, "forget");
  updateConfig({ bots: enabled.filter((b) => b !== bot) });
  writeBotsEnv(repoPath, { unset: BOT_ENV_KEYS[bot] });
  updateApiEnv(repoPath, { unset: [BOT_API_ENV_KEYS[bot]] });
  finishStep(store, "forget");
  await restartStack(store, repoPath);
  setEnding(store, {
    lead: "Add it back any time:",
    target: `gaia bots add ${bot}`,
  });
}

/** Run add or remove on the shared run screen; a throw becomes the screen's error. */
export async function runBotsCommand(
  runFlow: (store: CLIStore) => Promise<void>,
): Promise<void> {
  await runCommandUI({
    command: "bots",
    whenNonInteractive: "plain",
    runFlow,
    cancelHint: "Run the same command again to finish.",
  });
}

export async function runBotsList(): Promise<void> {
  await printHeader({ showStatus: false });
  await requireSelfhostInstall();
  const enabled = readConfig()?.bots ?? [];
  if (enabled.length === 0) {
    out("  No chat bots yet.");
    out();
    out("  Add one:  gaia bots add <telegram|discord|slack>");
    return;
  }
  const containers = await getComposeProjectContainers(
    COMPOSE_PROJECT_BY_MODE.selfhost,
  );
  for (const bot of enabled) {
    const state = botContainerState(bot, containers);
    const mark = {
      healthy: MARK.ok,
      starting: MARK.pending,
      failing: MARK.fail,
    }[state.health];
    out(`  ${mark} ${BOT_NAMES[bot].padEnd(10)}${state.detail}`);
  }
}

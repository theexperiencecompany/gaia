import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";
import { execa } from "execa";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GaiaConfig } from "../../src/lib/config.js";

const {
  config,
  detectSetupMode,
  findInstallRoot,
  isInteractive,
  runSelfhostOneOff,
  startServices,
} = vi.hoisted(() => ({
  config: { current: null as Partial<GaiaConfig> | null },
  detectSetupMode: vi.fn(),
  findInstallRoot: vi.fn(),
  isInteractive: vi.fn(),
  runSelfhostOneOff: vi.fn(),
  startServices: vi.fn(),
}));
vi.mock("execa", () => ({ execa: vi.fn() }));
vi.mock("../../src/lib/install-root.js", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/lib/install-root.js")>()),
  detectSetupMode,
  findInstallRoot,
}));
vi.mock("../../src/lib/service-starter.js", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("../../src/lib/service-starter.js")
  >()),
  runSelfhostOneOff,
  startServices,
}));
vi.mock("../../src/lib/config.js", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/lib/config.js")>()),
  readConfig: () => config.current,
  updateConfig: (partial: Partial<GaiaConfig>) => {
    config.current = { ...config.current, ...partial };
  },
}));
vi.mock("../../src/lib/non-tty.js", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/lib/non-tty.js")>()),
  isInteractive,
}));
// Each poll moves the clock by the interval instead of sleeping.
vi.mock("../../src/lib/flow-utils.js", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/lib/flow-utils.js")>()),
  delay: async (ms: number) => {
    vi.setSystemTime(Date.now() + ms);
  },
}));

import { runBotsAdd, runBotsRemove } from "../../src/commands/bots/handler.js";
import {
  BOT_CREDENTIAL_INPUT,
  type CredentialRequest,
} from "../../src/commands/bots/prompt.js";
import { parseEnvFileValues } from "../../src/lib/env-writer.js";
import { type CLIStore, createStore } from "../../src/ui/store.js";

const mockedExeca = vi.mocked(execa);
const TOKEN = "123:telegram-token"; // pragma: allowlist secret

const API_ENV = [
  "FRONTEND_URL=https://gaia.example.com",
  "RABBITMQ_URL=amqp://guest:guest@rabbitmq:5672/", // pragma: allowlist secret
].join("\n");

let repo: string;
let store: CLIStore;
/** What the screen was asked for, in order. */
let asked: CredentialRequest[];
/** What the person pastes, in order; the last one again on every later ask. */
let answers: string[];

/** A store whose screen answers each credential request with the next paste. */
function answeringStore(): CLIStore {
  const answering = createStore();
  answering.on("change", (state) => {
    const request = state.inputRequest;
    if (request?.id !== BOT_CREDENTIAL_INPUT) return;
    // Answered after waitForInput has its resolver, as a keypress would be.
    setImmediate(() => {
      if (answering.currentState.inputRequest !== request) return;
      asked.push(request.meta as CredentialRequest);
      answering.submitInput(answers.length > 1 ? answers.shift() : answers[0]);
    });
  });
  return answering;
}

function readEnv(app: "api" | "bots"): Record<string, string> {
  return parseEnvFileValues(
    readFileSync(path.join(repo, "apps", app, ".env"), "utf-8"),
  );
}

/** `docker ps` answers with each listed status line of the service in turn, then the last one forever. */
function containerStatuses(service: string, ...statuses: string[]): void {
  let call = 0;
  mockedExeca.mockImplementation((() => {
    const status = statuses[Math.min(call++, statuses.length - 1)];
    return Promise.resolve({ stdout: `${service}|${status}` });
  }) as unknown as typeof execa);
}

function botContainerStatuses(...statuses: string[]): void {
  containerStatuses("bot-telegram", ...statuses);
}

/** Every platform API call answers with this body. */
function platformAnswers(body: object): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json(body)),
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers({ toFake: ["Date"] });
  repo = mkdtempSync(path.join(tmpdir(), "gaia-bots-add-"));
  mkdirSync(path.join(repo, "apps", "api"), { recursive: true });
  mkdirSync(path.join(repo, "apps", "bots"), { recursive: true });
  writeFileSync(path.join(repo, "apps", "api", ".env"), API_ENV);
  config.current = null;
  asked = [];
  answers = [];
  store = answeringStore();
  startServices.mockResolvedValue({ startedServices: 1 });
  findInstallRoot.mockReturnValue(repo);
  detectSetupMode.mockResolvedValue("selfhost");
  isInteractive.mockReturnValue(true);
  vi.spyOn(process.stdout, "write").mockReturnValue(true);
  platformAnswers({ ok: true, result: { username: "my_gaia_bot" } });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  rmSync(repo, { recursive: true, force: true });
});

describe("gaia bots add", () => {
  it("asks for a missing token, starts the bot and waits until it is healthy", async () => {
    answers = [TOKEN];
    botContainerStatuses(
      "running|Up 5 seconds (health: starting)",
      "running|Up 30 seconds (healthy)",
    );

    await runBotsAdd(store, "telegram", {});

    expect(asked[0]?.label).toBe("Telegram bot token");
    expect(vi.mocked(fetch).mock.calls[0]?.[0]).toBe(
      `https://api.telegram.org/bot${TOKEN}/getMe`,
    );
    expect(config.current?.bots).toEqual(["telegram"]);
    expect(startServices).toHaveBeenCalledOnce();
    expect(runSelfhostOneOff).toHaveBeenCalledWith(repo, "bot-telegram", [
      "node",
      "dist/set-commands.js",
    ]);
    expect(mockedExeca).toHaveBeenCalledTimes(2);
  });

  it("generates the bot key into an install that has none and shares it with the bot", async () => {
    botContainerStatuses("running|Up 30 seconds (healthy)");

    await runBotsAdd(store, "telegram", { token: TOKEN });

    const apiEnv = readEnv("api");
    const botsEnv = readEnv("bots");
    expect(apiEnv.GAIA_BOT_API_KEY).toMatch(/^[0-9a-f]{64}$/);
    expect(botsEnv.GAIA_BOT_API_KEY).toBe(apiEnv.GAIA_BOT_API_KEY);
    expect(botsEnv.TELEGRAM_BOT_TOKEN).toBe(TOKEN);
    expect(apiEnv.TELEGRAM_BOT_USERNAME).toBe("my_gaia_bot");
  });

  it("names the flag and where to get the token when there is no terminal to ask in", async () => {
    isInteractive.mockReturnValue(false);

    await expect(runBotsAdd(store, "telegram", {})).rejects.toThrow(
      /Missing --token\. .*@BotFather/,
    );
    expect(asked).toEqual([]);
    expect(startServices).not.toHaveBeenCalled();
    expect(config.current).toBeNull();
  });

  it("asks for every Slack credential not passed as a flag", async () => {
    isInteractive.mockReturnValue(false);

    await expect(
      runBotsAdd(store, "slack", { token: "xoxb-1" }),
    ).rejects.toThrow("Missing --app-token");
  });

  it("fails with the way to the logs when the bot never becomes healthy", async () => {
    botContainerStatuses("restarting|Restarting (1) 4 seconds ago");

    await expect(
      runBotsAdd(store, "telegram", { token: TOKEN }),
    ).rejects.toThrow(
      "did not come up (restarting).\nSee why with 'docker compose -p gaia-selfhost logs bot-telegram'",
    );
  });

  it("names the Discord app to the web app, for its invite link", async () => {
    platformAnswers({ id: "4242", flags: 1 << 18 });
    containerStatuses("bot-discord", "running|Up 30 seconds (healthy)");

    await runBotsAdd(store, "discord", { token: TOKEN });

    expect(readEnv("api").DISCORD_CLIENT_ID).toBe("4242");
  });

  it("names the Slack workspace to the web app", async () => {
    platformAnswers({
      ok: true,
      team: "Acme",
      url: "https://acme.slack.com/",
    });
    containerStatuses("bot-slack", "running|Up 30 seconds (healthy)");

    await runBotsAdd(store, "slack", {
      token: "xoxb-1",
      appToken: "xapp-1",
      signingSecret: "s",
    });

    expect(readEnv("api").SLACK_WORKSPACE_URL).toBe("https://acme.slack.com/");
  });

  it("refuses a machine without a self-host install before asking for anything", async () => {
    detectSetupMode.mockResolvedValue("developer");

    await expect(runBotsAdd(store, "telegram", {})).rejects.toThrow(
      "No self-host GAIA install found",
    );
    expect(asked).toEqual([]);
  });
});

describe("gaia bots remove", () => {
  it("forgets the bot's handle so the web app stops offering it", async () => {
    writeFileSync(
      path.join(repo, "apps", "api", ".env"),
      `${API_ENV}\nSLACK_WORKSPACE_URL=https://acme.slack.com/`,
    );
    config.current = { bots: ["slack"] };

    await runBotsRemove(store, "slack");

    expect(readEnv("api")).not.toHaveProperty("SLACK_WORKSPACE_URL");
    expect(config.current?.bots).toEqual([]);
  });
});
describe("gaia bots add with a pasted token the platform rejects", () => {
  it("asks again in place instead of exiting, and goes on with the good token", async () => {
    answers = ["bad-token", TOKEN];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        Response.json(
          url.includes("bad-token")
            ? { ok: false, description: "Unauthorized" }
            : { ok: true, result: { username: "my_gaia_bot" } },
        ),
      ),
    );
    botContainerStatuses("running|Up 30 seconds (healthy)");

    await runBotsAdd(store, "telegram", {});

    expect(asked).toHaveLength(2);
    expect(config.current?.bots).toEqual(["telegram"]);
  });

  it("asks for the one token as 'it' and gives the BotFather hint once", async () => {
    answers = ["bad-token", TOKEN];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        Response.json(
          url.includes("bad-token")
            ? { ok: false, description: "Unauthorized" }
            : { ok: true, result: { username: "my_gaia_bot" } },
        ),
      ),
    );
    botContainerStatuses("running|Up 30 seconds (healthy)");

    await runBotsAdd(store, "telegram", {});

    expect(asked[1]?.retry).toContain("Paste it again (2 tries left)");
    expect(
      asked.filter((request) =>
        request.hint?.includes("@BotFather, send /newbot"),
      ),
    ).toHaveLength(1);
  });

  it("stops after three rejected tries", async () => {
    answers = ["bad-token"];
    platformAnswers({ ok: false, description: "Unauthorized" });

    await expect(runBotsAdd(store, "telegram", {})).rejects.toThrow(
      "Telegram rejected the bot token: Unauthorized.",
    );
    expect(asked).toHaveLength(3);
    expect(config.current).toBeNull();
  });

  it("fails at once on a rejected --token flag: nobody is there to paste again", async () => {
    platformAnswers({ ok: false, description: "Unauthorized" });

    await expect(
      runBotsAdd(store, "telegram", { token: "bad" }),
    ).rejects.toThrow("Telegram rejected the bot token");
    expect(asked).toEqual([]);
  });
});

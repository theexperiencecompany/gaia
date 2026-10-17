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
  askSecret,
  config,
  detectSetupMode,
  findInstallRoot,
  isInteractive,
  runSelfhostOneOff,
  startServices,
} = vi.hoisted(() => ({
  askSecret: vi.fn(),
  config: { current: null as Partial<GaiaConfig> | null },
  detectSetupMode: vi.fn(),
  findInstallRoot: vi.fn(),
  isInteractive: vi.fn(),
  runSelfhostOneOff: vi.fn(),
  startServices: vi.fn(),
}));
vi.mock("execa", () => ({ execa: vi.fn() }));
vi.mock("../../src/lib/service-starter.js", () => ({
  detectSetupMode,
  findInstallRoot,
  runSelfhostOneOff,
  startServices,
}));
vi.mock("../../src/lib/config.js", () => ({
  readConfig: () => config.current,
  updateConfig: (partial: Partial<GaiaConfig>) => {
    config.current = { ...config.current, ...partial };
  },
}));
vi.mock("../../src/lib/non-tty.js", () => ({ isInteractive }));
vi.mock("../../src/lib/prompt.js", () => ({ askSecret }));
// Each poll moves the clock by the interval instead of sleeping.
vi.mock("../../src/lib/flow-utils.js", () => ({
  delay: async (ms: number) => {
    vi.setSystemTime(Date.now() + ms);
  },
}));

import { runBotsAdd, runBotsRemove } from "../../src/commands/bots/handler.js";
import { parseEnvFileValues } from "../../src/lib/env-writer.js";

const mockedExeca = vi.mocked(execa);
const TOKEN = "123:telegram-token"; // pragma: allowlist secret

const API_ENV = [
  "FRONTEND_URL=https://gaia.example.com",
  "RABBITMQ_URL=amqp://guest:guest@rabbitmq:5672/", // pragma: allowlist secret
].join("\n");

let repo: string;

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
    askSecret.mockResolvedValue(TOKEN);
    botContainerStatuses(
      "running|Up 5 seconds (health: starting)",
      "running|Up 30 seconds (healthy)",
    );

    await runBotsAdd("telegram", {});

    expect(askSecret).toHaveBeenCalledWith("Telegram bot token");
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

    await runBotsAdd("telegram", { token: TOKEN });

    const apiEnv = readEnv("api");
    const botsEnv = readEnv("bots");
    expect(apiEnv.GAIA_BOT_API_KEY).toMatch(/^[0-9a-f]{64}$/);
    expect(botsEnv.GAIA_BOT_API_KEY).toBe(apiEnv.GAIA_BOT_API_KEY);
    expect(botsEnv.TELEGRAM_BOT_TOKEN).toBe(TOKEN);
    expect(apiEnv.TELEGRAM_BOT_USERNAME).toBe("my_gaia_bot");
  });

  it("names the flag and where to get the token when there is no terminal to ask in", async () => {
    isInteractive.mockReturnValue(false);

    await expect(runBotsAdd("telegram", {})).rejects.toThrow(
      /Missing --token\. .*@BotFather/,
    );
    expect(askSecret).not.toHaveBeenCalled();
    expect(startServices).not.toHaveBeenCalled();
    expect(config.current).toBeNull();
  });

  it("asks for every Slack credential not passed as a flag", async () => {
    isInteractive.mockReturnValue(false);

    await expect(runBotsAdd("slack", { token: "xoxb-1" })).rejects.toThrow(
      "Missing --app-token",
    );
  });

  it("fails with the way to the logs when the bot never becomes healthy", async () => {
    botContainerStatuses("restarting|Restarting (1) 4 seconds ago");

    await expect(runBotsAdd("telegram", { token: TOKEN })).rejects.toThrow(
      "did not come up (restarting). See why with 'docker compose -p gaia-selfhost logs bot-telegram'",
    );
  });

  it("names the Discord app to the web app, for its invite link", async () => {
    platformAnswers({ id: "4242", flags: 1 << 18 });
    containerStatuses("bot-discord", "running|Up 30 seconds (healthy)");

    await runBotsAdd("discord", { token: TOKEN });

    expect(readEnv("api").DISCORD_CLIENT_ID).toBe("4242");
  });

  it("names the Slack workspace to the web app", async () => {
    platformAnswers({
      ok: true,
      team: "Acme",
      url: "https://acme.slack.com/",
    });
    containerStatuses("bot-slack", "running|Up 30 seconds (healthy)");

    await runBotsAdd("slack", {
      token: "xoxb-1",
      appToken: "xapp-1",
      signingSecret: "s",
    });

    expect(readEnv("api").SLACK_WORKSPACE_URL).toBe("https://acme.slack.com/");
  });

  it("refuses a machine without a self-host install before asking for anything", async () => {
    detectSetupMode.mockResolvedValue("developer");

    await expect(runBotsAdd("telegram", {})).rejects.toThrow(
      "No self-host GAIA install found",
    );
    expect(askSecret).not.toHaveBeenCalled();
  });
});

describe("gaia bots remove", () => {
  it("forgets the bot's handle so the web app stops offering it", async () => {
    writeFileSync(
      path.join(repo, "apps", "api", ".env"),
      `${API_ENV}\nSLACK_WORKSPACE_URL=https://acme.slack.com/`,
    );
    config.current = { bots: ["slack"] };

    await runBotsRemove("slack");

    expect(readEnv("api")).not.toHaveProperty("SLACK_WORKSPACE_URL");
    expect(config.current?.bots).toEqual([]);
  });
});
describe("gaia bots add with a pasted token the platform rejects", () => {
  it("asks again in place instead of exiting, and goes on with the good token", async () => {
    askSecret.mockResolvedValueOnce("bad-token").mockResolvedValueOnce(TOKEN);
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

    await runBotsAdd("telegram", {});

    expect(askSecret).toHaveBeenCalledTimes(2);
    expect(config.current?.bots).toEqual(["telegram"]);
  });

  it("asks for the one token as 'it' and gives the BotFather hint once", async () => {
    let text = "";
    vi.spyOn(process.stdout, "write").mockImplementation((chunk) => {
      text += String(chunk);
      return true;
    });
    askSecret.mockResolvedValueOnce("bad-token").mockResolvedValueOnce(TOKEN);
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

    await runBotsAdd("telegram", {});

    expect(text).toContain("Paste it again (2 tries left)");
    expect(text.match(/@BotFather, send \/newbot/g)).toHaveLength(1);
  });

  it("stops after three rejected tries", async () => {
    askSecret.mockResolvedValue("bad-token");
    platformAnswers({ ok: false, description: "Unauthorized" });

    await expect(runBotsAdd("telegram", {})).rejects.toThrow(
      "Telegram rejected the bot token: Unauthorized.",
    );
    expect(askSecret).toHaveBeenCalledTimes(3);
    expect(config.current).toBeNull();
  });

  it("fails at once on a rejected --token flag: nobody is there to paste again", async () => {
    platformAnswers({ ok: false, description: "Unauthorized" });

    await expect(runBotsAdd("telegram", { token: "bad" })).rejects.toThrow(
      "Telegram rejected the bot token",
    );
    expect(askSecret).not.toHaveBeenCalled();
  });
});

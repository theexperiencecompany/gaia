// `gaia bridge` — connects this machine's MCP servers and files to GAIA over
// one secure outbound tunnel.

import { Command } from "commander";
import { CLI_COMMAND_DESCRIPTIONS } from "../../../../../libs/shared/ts/src/cli/command-manifest.js";
import { runAction } from "../../lib/command-action.js";
import {
  apiUrlFromEnvOrCreds,
  clearCredentials,
  loadConfig,
  loadCredentials,
} from "./config.js";
import { runLogin } from "./login.js";
import { daemonStatusLine, runServe, runUp, stopDaemon } from "./up.js";
import { type AddOptions, runAdd, runRemove } from "./wizard.js";

function cmdList(): void {
  const creds = loadCredentials();
  console.info(
    creds?.deviceId
      ? `Paired (device ${creds.deviceId}, ${apiUrlFromEnvOrCreds()})`
      : "Not paired — run: gaia bridge login",
  );
  console.info(daemonStatusLine());
  const servers = loadConfig().servers;
  if (servers.length === 0) {
    console.info("No servers configured — run: gaia bridge add");
    return;
  }
  console.info("\nConfigured servers:");
  for (const s of servers) {
    if (s.type === "filesystem") {
      console.info(
        `  [${s.key}] filesystem${s.allowWrite ? " (rw)" : " (ro)"}: ${s.allow.join(", ")}`,
      );
    } else if (s.type === "stdio") {
      const names = Object.keys(s.env);
      console.info(`  [${s.key}] ${s.name}: ${s.command} ${s.args.join(" ")}`);
      if (names.length) console.info(`  env: ${names.join(", ")}`);
    } else {
      console.info(`  [${s.key}] ${s.name}: ${s.url}`);
      const headerNames = s.headers ? Object.keys(s.headers) : [];
      if (headerNames.length)
        console.info(`  headers: ${headerNames.join(", ")}`);
    }
  }
}

export const bridgeCommand = new Command("bridge")
  .description(CLI_COMMAND_DESCRIPTIONS.bridge)
  .addHelpText(
    "after",
    "\nRevoke a device anytime from GAIA → Settings → Devices.",
  );

bridgeCommand
  .command("add")
  .description(
    "Connect a local MCP server (guided; or non-interactive with --type)",
  )
  .option(
    "--type <type>",
    "stdio | url — enables non-interactive mode (no prompts)",
  )
  .option("--name <name>", "display name")
  .option("--command <command>", "stdio: the command that starts the server")
  .option("--url <url>", "url: the local MCP server URL")
  .option("--env <pair...>", "stdio: KEY=VALUE env var (repeatable)")
  .option("--header <pair...>", "url: Header:Value request header (repeatable)")
  .action(async (opts: AddOptions) => {
    await runAction(() => runAdd(opts));
  });

bridgeCommand
  .command("login")
  .description("Pair this machine with your GAIA account")
  .option(
    "--api <url>",
    "GAIA API base URL (default: this machine's self-host install, else GAIA Cloud)",
  )
  .option("--name <name>", "Name to show for this device in Settings")
  .action(async (options: { api?: string; name?: string }) => {
    await runAction(async () => {
      await runLogin({
        ...(options.api !== undefined ? { api: options.api } : {}),
        ...(options.name !== undefined ? { name: options.name } : {}),
      });
      console.info("Next: gaia bridge add");
    });
  });

bridgeCommand
  .command("ls")
  .alias("list")
  .description("Show pairing status and configured servers")
  .action(async () => {
    await runAction(cmdList);
  });

bridgeCommand
  .command("remove")
  .alias("rm")
  .description(
    "Remove a configured server (interactive picker if no key given)",
  )
  .argument("[key]", "Server key from `gaia bridge ls` (optional)")
  .action(async (key: string | undefined) => {
    await runAction(() => runRemove(key));
  });

bridgeCommand
  .command("up")
  .alias("start")
  .description(
    "Connect with full file access + serve in the background (stop with: gaia bridge down)",
  )
  .option(
    "--serve",
    "(internal) hold the tunnel in the foreground; used by the background daemon",
  )
  .action(async (options: { serve?: boolean }) => {
    await runAction(options.serve ? runServe : runUp);
  });

bridgeCommand
  .command("down")
  .alias("stop")
  .description("Stop the background tunnel started by `gaia bridge up`")
  .action(async () => {
    await runAction(stopDaemon);
  });

bridgeCommand
  .command("logout")
  .description("Forget local credentials")
  .action(async () => {
    await runAction(() => {
      clearCredentials();
      console.info(
        "Logged out. Your device record remains until you revoke it in GAIA settings.",
      );
    });
  });

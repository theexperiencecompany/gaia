// `gaia bridge` — connects this machine's MCP servers and files to GAIA over
// one secure outbound tunnel.

import { Command } from "commander";
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

/** Commander swallows async rejections, so every action reports its own failure. */
async function run(action: () => void | Promise<void>): Promise<void> {
  try {
    await action();
  } catch (error) {
    console.error(
      `Error: ${error instanceof Error ? error.message : String(error)}`,
    );
    process.exit(1);
  }
}

export const bridgeCommand = new Command("bridge")
  .description(
    "Connect this machine's local MCP servers and files to GAIA (outbound-only, no inbound ports)",
  )
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
    await run(() => runAdd(opts));
  });

bridgeCommand
  .command("login")
  .description("Pair this machine with your GAIA account")
  .option("--api <url>", "GAIA API base URL")
  .option("--name <name>", "Name to show for this device in Settings")
  .action(async (options: { api?: string; name?: string }) => {
    await run(async () => {
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
    await run(cmdList);
  });

bridgeCommand
  .command("remove")
  .alias("rm")
  .description(
    "Remove a configured server (interactive picker if no key given)",
  )
  .argument("[key]", "Server key from `gaia bridge ls` (optional)")
  .action(async (key: string | undefined) => {
    await run(() => runRemove(key));
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
    await run(options.serve ? runServe : runUp);
  });

bridgeCommand
  .command("down")
  .alias("stop")
  .description("Stop the background tunnel started by `gaia bridge up`")
  .action(async () => {
    await run(stopDaemon);
  });

bridgeCommand
  .command("logout")
  .description("Forget local credentials")
  .action(async () => {
    await run(() => {
      clearCredentials();
      console.info(
        "Logged out. Your device record remains until you revoke it in GAIA settings.",
      );
    });
  });

// `gaia bridge` — connects this machine's MCP servers and files to GAIA over
// one secure outbound tunnel.

import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { Command } from "commander";
import {
  apiUrlFromEnvOrCreds,
  clearCredentials,
  loadConfig,
  loadCredentials,
  removeServer,
  upsertServer,
} from "./config.js";
import { FILESYSTEM_SERVER_KEY } from "./constants.js";
import { runLogin } from "./login.js";
import { runUp } from "./up.js";
import { runAdd } from "./wizard.js";

/** Expand a leading ~ so quoted paths like "~/Documents" still resolve to $HOME. */
function expandTilde(p: string): string {
  if (p === "~") return homedir();
  if (p.startsWith("~/")) return join(homedir(), p.slice(2));
  return p;
}

function cmdFs(dirs: string[], write: boolean): void {
  const allow = dirs.map((p) => resolve(expandTilde(p)));
  upsertServer({
    type: "filesystem",
    key: FILESYSTEM_SERVER_KEY,
    name: "Local Files",
    allow,
    allowWrite: write,
  });
  console.info(
    `Filesystem access configured for:\n  ${allow.join("\n  ")}\n` +
      `Writes: ${write ? "ENABLED" : "disabled (read-only)"}\n` +
      `Run: gaia bridge up`,
  );
}

function cmdList(): void {
  const creds = loadCredentials();
  console.info(
    creds?.deviceId
      ? `Paired (device ${creds.deviceId}, ${apiUrlFromEnvOrCreds()})`
      : "Not paired — run: gaia bridge login",
  );
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
  .description("Connect a local MCP server (guided — start here!)")
  .action(async () => {
    await run(runAdd);
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
  .command("fs")
  .description("Expose folders for file access (read-only unless --write)")
  .argument("<dirs...>", "Folders to expose, e.g. ~/Documents")
  .option("--write", "Allow GAIA to write to these folders")
  .action(async (dirs: string[], options: { write?: boolean }) => {
    await run(() => cmdFs(dirs, options.write === true));
  });

bridgeCommand
  .command("ls")
  .alias("list")
  .description("Show pairing status and configured servers")
  .action(async () => {
    await run(cmdList);
  });

bridgeCommand
  .command("rm")
  .alias("remove")
  .description("Remove a configured server")
  .argument("<key>", "Server key from `gaia bridge ls`")
  .action(async (key: string) => {
    await run(() => {
      console.info(
        removeServer(key) ? `Removed '${key}'` : `No server '${key}'`,
      );
    });
  });

bridgeCommand
  .command("up")
  .alias("start")
  .description("Connect and serve (holds the tunnel; Ctrl+C to stop)")
  .action(async () => {
    await run(runUp);
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

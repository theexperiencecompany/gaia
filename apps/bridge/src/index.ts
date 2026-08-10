// gaia — the GAIA CLI. `gaia bridge` connects your machine's MCP servers and
// files to GAIA over one secure outbound tunnel.

import { homedir } from "node:os";
import { join, resolve } from "node:path";
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
import { VERSION } from "./version.js";
import { runAdd } from "./wizard.js";

function fail(message: string): never {
  console.error(`Error: ${message}`);
  process.exit(1);
}

/** Parse `--flag value` and boolean `--flag` out of argv, returning the rest. */
function parseFlags(
  args: string[],
  booleans: string[] = [],
): { flags: Record<string, string | boolean>; positionals: string[] } {
  const flags: Record<string, string | boolean> = {};
  const positionals: string[] = [];
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === undefined) continue;
    if (arg.startsWith("--")) {
      const name = arg.slice(2);
      if (booleans.includes(name)) {
        flags[name] = true;
      } else {
        const value = args[++i];
        if (value === undefined) fail(`missing value for --${name}`);
        flags[name] = value;
      }
    } else {
      positionals.push(arg);
    }
  }
  return { flags, positionals };
}

/** Expand a leading ~ so quoted paths like "~/Documents" still resolve to $HOME. */
function expandTilde(p: string): string {
  if (p === "~") return homedir();
  if (p.startsWith("~/")) return join(homedir(), p.slice(2));
  return p;
}

function cmdFs(args: string[]): void {
  const { flags, positionals } = parseFlags(args, ["write"]);
  if (positionals.length === 0)
    fail("usage: gaia bridge fs <dir> [<dir>…] [--write]");
  const allow = positionals.map((p) => resolve(expandTilde(p)));
  upsertServer({
    type: "filesystem",
    key: FILESYSTEM_SERVER_KEY,
    name: "Local Files",
    allow,
    allowWrite: flags["write"] === true,
  });
  console.info(
    `Filesystem access configured for:\n  ${allow.join("\n  ")}\n` +
      `Writes: ${flags["write"] === true ? "ENABLED" : "disabled (read-only)"}\n` +
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

function cmdRemove(args: string[]): void {
  const key = args[0];
  if (!key) fail("usage: gaia bridge rm <key>");
  console.info(removeServer(key) ? `Removed '${key}'` : `No server '${key}'`);
}

function cmdLogout(): void {
  clearCredentials();
  console.info(
    "Logged out. Your device record remains until you revoke it in GAIA settings.",
  );
}

function printHelp(): void {
  console.info(`gaia ${VERSION} — GAIA on your machine

Usage: gaia bridge <command>

  add                                Connect a local MCP server (guided — start here!)
  login [--api <url>] [--name <n>]   Pair this machine with your GAIA account
  fs <dir> [<dir>…] [--write]        Expose folders for file access (read-only unless --write)
  ls                                 Show pairing status and configured servers
  rm <key>                           Remove a configured server
  up                                 Connect and serve (holds the tunnel; Ctrl+C to stop)
  logout                             Forget local credentials

Examples:
  gaia bridge add                    Connect any local MCP server in one guided flow
  gaia bridge fs ~/Documents         Let GAIA read files in ~/Documents

The connection is outbound-only (no inbound ports). Revoke a device anytime from
GAIA → Settings → Devices.`);
}

async function runBridge(args: string[]): Promise<void> {
  const [command, ...rest] = args;
  switch (command) {
    case "login": {
      const { flags } = parseFlags(rest);
      const api = flags["api"];
      const name = flags["name"];
      await runLogin({
        ...(typeof api === "string" ? { api } : {}),
        ...(typeof name === "string" ? { name } : {}),
      });
      console.info("Next: gaia bridge add");
      break;
    }
    case "add":
      await runAdd();
      break;
    case "fs":
      cmdFs(rest);
      break;
    case "ls":
    case "list":
      cmdList();
      break;
    case "rm":
    case "remove":
      cmdRemove(rest);
      break;
    case "up":
    case "start":
      await runUp();
      break;
    case "logout":
      cmdLogout();
      break;
    case "help":
    case "--help":
    case "-h":
    case undefined:
      printHelp();
      break;
    default:
      fail(`unknown command 'bridge ${command}' — run: gaia bridge help`);
  }
}

async function main(): Promise<void> {
  const [group, ...rest] = process.argv.slice(2);
  switch (group) {
    case "bridge":
      await runBridge(rest);
      break;
    case "help":
    case "--help":
    case "-h":
    case undefined:
      printHelp();
      break;
    case "--version":
    case "-v":
      console.info(VERSION);
      break;
    default:
      fail(`unknown command '${group}' — run: gaia help`);
  }
}

main().catch((e) => fail(e instanceof Error ? e.message : String(e)));

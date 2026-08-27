// `gaia bridge add` — guided setup for connecting ANY local MCP server.
// One command takes a user from nothing to working tools: pair (if needed) →
// how does the server run (command or URL) → env vars → verify it actually
// starts and lists tools → save → offer to bring the tunnel up.

import { basename } from "node:path";
import { loadConfig, upsertServer } from "./config.js";
import type { ServerConfig } from "./config.types.js";
import { FILESYSTEM_SERVER_KEY } from "./constants.js";
import { isPaired, runLogin } from "./login.js";
import { ask, askSecret, choose, confirm } from "./prompt.js";
import { testServer } from "./servers.js";
import { runUp } from "./up.js";

function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
}

/** Split a command line into command + args, honoring single/double quotes. */
function tokenizeCommand(line: string): {
  command: string;
  args: string[];
} {
  const tokens: string[] = [];
  let current = "";
  let quote: '"' | "'" | null = null;
  for (const ch of line.trim()) {
    if (quote) {
      if (ch === quote) quote = null;
      else current += ch;
    } else if (ch === '"' || ch === "'") {
      quote = ch;
    } else if (/\s/.test(ch)) {
      if (current) {
        tokens.push(current);
        current = "";
      }
    } else {
      current += ch;
    }
  }
  if (current) tokens.push(current);
  const [command, ...args] = tokens;
  if (!command) throw new Error("Empty command");
  return { command, args };
}

/** Best-guess display name from the command line, e.g. "npx -y my-server@1.2" → "my-server". */
function suggestNameFromCommand(command: string, args: string[]): string {
  const candidates = [...args].reverse().filter((a) => !a.startsWith("-"));
  const source = candidates[0] ?? command;
  return basename(source).replace(/@[^@]*$/, "");
}

function suggestNameFromUrl(url: string): string {
  try {
    const parsed = new URL(url);
    return parsed.port ? `local-${parsed.port}` : parsed.hostname;
  } catch {
    return "";
  }
}

async function askName(
  suggested: string,
): Promise<{ name: string; key: string }> {
  for (;;) {
    const name = await ask("Name for this server", suggested);
    const key = slugify(name);
    if (!name || !key || key === FILESYSTEM_SERVER_KEY) {
      console.info("Pick a different name.");
      continue;
    }
    if (loadConfig().servers.some((s) => s.key === key)) {
      const overwrite = await confirm(
        `'${key}' already exists — overwrite?`,
        false,
      );
      if (!overwrite) continue;
    }
    return { name, key };
  }
}

/** Env var names a `docker run` command passes through (`-e NAME` without `=value`). */
function discoverEnvVarNames(command: string, args: string[]): string[] {
  if (basename(command) !== "docker") return [];
  const names: string[] = [];
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === undefined) continue;
    if (arg === "-e" || arg === "--env") {
      const next = args[i + 1];
      if (next && !next.includes("=")) names.push(next);
    } else if (arg.startsWith("-e") && arg.length > 2 && !arg.includes("=")) {
      names.push(arg.slice(2));
    }
  }
  return [...new Set(names)];
}

/** Resolve one variable's value: grab it from the environment (no paste) or take a typed value. */
async function promptForVar(name: string): Promise<string> {
  const inEnv = process.env[name];
  if (inEnv !== undefined && inEnv !== "") {
    if (
      await confirm(
        `  Found ${name} in your environment — use that value?`,
        true,
      )
    ) {
      return inEnv;
    }
  }
  for (;;) {
    const value = await askSecret(`  Paste ${name}`);
    if (value) {
      console.info(`  Got it (${value.length} characters).`);
      return value;
    }
    console.info("  Empty — paste the value, or Ctrl+C to abort.");
  }
}

async function collectEnv(
  command: string,
  args: string[],
): Promise<Record<string, string>> {
  const env: Record<string, string> = {};

  for (const name of discoverEnvVarNames(command, args)) {
    console.info(`\nThe command needs ${name}.`);
    env[name] = await promptForVar(name);
  }

  const opener = Object.keys(env).length
    ? "Any other environment variables to add?"
    : "Does the server need environment variables (API keys, tokens…)?";
  if (!(await confirm(opener, false))) return env;

  console.info("Enter each variable's name; leave blank when done.");
  for (;;) {
    const name = (await ask("  Variable name")).trim();
    if (!name) break;
    if (name in env) {
      console.info("  Already added.");
      continue;
    }
    env[name] = await promptForVar(name);
  }
  return env;
}

async function buildStdioConfig(): Promise<ServerConfig> {
  console.info(
    "\nExamples:  npx -y my-mcp-server   ·   uvx my-server   ·   docker run -i --rm my/image",
  );
  const commandLine = await ask("Command that starts your MCP server");
  if (!commandLine) throw new Error("a command is required");
  const { command, args } = tokenizeCommand(commandLine);
  const env = await collectEnv(command, args);
  const { name, key } = await askName(suggestNameFromCommand(command, args));
  return { type: "stdio", key, name, command, args, env };
}

async function buildUrlConfig(): Promise<ServerConfig> {
  const url = await ask("Server URL (e.g. http://localhost:3000/mcp)");
  if (!url) throw new Error("a URL is required");
  const { name, key } = await askName(suggestNameFromUrl(url));
  return { type: "url", key, name, url };
}

async function verifyServer(config: ServerConfig): Promise<boolean> {
  for (;;) {
    console.info(
      "\nTesting the connection (this may download/start the server)…",
    );
    try {
      const tools = await testServer(config);
      const sample = tools.slice(0, 5).join(", ");
      console.info(
        `Connected — ${tools.length} tools found${sample ? ` (${sample}${tools.length > 5 ? ", …" : ""})` : ""}.`,
      );
      return true;
    } catch (e) {
      console.error(`Connection failed: ${e instanceof Error ? e.message : e}`);
      const options = ["Retry the test"];
      if (config.type === "stdio")
        options.push("Re-enter environment variables");
      options.push("Save anyway (fix it later)", "Abort");

      const label = options[await choose("What now?", options)];
      if (
        label === "Re-enter environment variables" &&
        config.type === "stdio"
      ) {
        config.env = await collectEnv(config.command, config.args);
      } else if (label === "Save anyway (fix it later)") {
        return true;
      } else if (label === "Abort") {
        return false;
      }
      // "Retry the test" (or after re-entering) → loop and test again.
    }
  }
}

export async function runAdd(): Promise<void> {
  if (!isPaired()) {
    console.info(
      "This device isn't paired with GAIA yet — let's do that first.",
    );
    await runLogin();
  }

  const kind = await choose("How does your MCP server run?", [
    "A command starts it (stdio) — npx / uvx / docker / python …",
    "It's already running at a local URL — e.g. http://localhost:3000/mcp",
  ]);
  const config = kind === 0 ? await buildStdioConfig() : await buildUrlConfig();

  if (!(await verifyServer(config))) throw new Error("aborted");

  upsertServer(config);
  console.info(`\nSaved '${config.key}'.`);

  if (await confirm("Connect to GAIA now (gaia bridge up)?")) {
    await runUp();
  } else {
    console.info("Run `gaia bridge up` whenever you're ready.");
  }
}

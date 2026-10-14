// Non-interactive server-config building: every value comes from a flag, so a
// host with no stdin (e.g. `run_on_device`) can set up a server without any of
// the wizard's prompts. Pure — no I/O, no prompts.

import { resolve } from "node:path";
import { expandTilde, filesystemServer } from "./config.js";
import type { ServerConfig } from "./config.types.js";
import { ENTIRE_FS_ROOT, FILESYSTEM_SERVER_KEY } from "./constants.js";
import { assertLoopbackUrl } from "./servers.js";

export function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
}

/** Split a command line into command + args, honoring single/double quotes. */
export function tokenizeCommand(line: string): {
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

// Non-interactive add: every value comes from a flag, so `run_on_device` (which
// has no stdin) can set up a server without hitting the wizard's prompts.
export interface AddOptions {
  type?: string;
  name?: string;
  command?: string;
  url?: string;
  path?: string[];
  write?: boolean;
  env?: string[];
  header?: string[];
}

export function parsePairs(
  items: string[] | undefined,
  sep: string,
  flag: string,
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const item of items ?? []) {
    const at = item.indexOf(sep);
    if (at <= 0)
      throw new Error(`invalid ${flag} '${item}', expected KEY${sep}VALUE`);
    out[item.slice(0, at).trim()] = item.slice(at + 1);
  }
  return out;
}

export function keyFromName(name: string | undefined): string {
  const key = slugify(name ?? "");
  if (!name || !key || key === FILESYSTEM_SERVER_KEY) {
    throw new Error("--name is required and must contain letters or digits");
  }
  return key;
}

export function buildConfigFromFlags(opts: AddOptions): ServerConfig {
  if (opts.type === "stdio") {
    if (!opts.command)
      throw new Error("--command is required for --type stdio");
    const { command, args } = tokenizeCommand(opts.command);
    return {
      type: "stdio",
      key: keyFromName(opts.name),
      name: opts.name as string,
      command,
      args,
      env: parsePairs(opts.env, "=", "--env"),
    };
  }
  if (opts.type === "url") {
    if (!opts.url) throw new Error("--url is required for --type url");
    assertLoopbackUrl(opts.url);
    const headers = parsePairs(opts.header, ":", "--header");
    if (
      Object.keys(headers).length > 0 &&
      new URL(opts.url).protocol === "http:"
    ) {
      // No prompt possible here: warn loudly instead of silently persisting
      // secrets that travel unencrypted (the interactive wizard confirms).
      console.warn(
        "warning: --header values travel unencrypted over local HTTP — " +
          "prefer an https: URL for credential headers",
      );
    }
    return {
      type: "url",
      key: keyFromName(opts.name),
      name: opts.name as string,
      url: opts.url,
      ...(Object.keys(headers).length ? { headers } : {}),
    };
  }
  if (opts.type === "filesystem") {
    const paths = opts.path ?? [];
    if (paths.length === 0)
      throw new Error("--path is required for --type filesystem");
    const allow = paths.includes(ENTIRE_FS_ROOT)
      ? [ENTIRE_FS_ROOT]
      : paths.map((p) => resolve(expandTilde(p)));
    return filesystemServer(allow, Boolean(opts.write));
  }
  throw new Error("--type must be one of: stdio, url, filesystem");
}

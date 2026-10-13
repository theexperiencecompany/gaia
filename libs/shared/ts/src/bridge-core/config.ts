// Persistent state on the user's machine: credentials (secret, 0600) and the
// list of MCP servers this device exposes. Lives under the injected state dir
// (the CLI's default is ~/.gaia/bridge/).

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import type {
  Credentials,
  FilesystemServer,
  ServerConfig,
} from "./config.types.js";
import { DEFAULT_API_URL, FILESYSTEM_SERVER_KEY } from "./constants.js";
import { bridgeEnv } from "./env.js";
import { assertLoopbackUrl } from "./servers.js";

interface BridgeConfig {
  servers: ServerConfig[];
}

// Resolved per call — not at module load — so a configureBridge() after import
// (e.g. the desktop host pointing state at userData/bridge) takes effect.
function configDir(): string {
  return bridgeEnv().stateDir;
}
function credentialsPath(): string {
  return join(configDir(), "credentials.json");
}
function configPath(): string {
  return join(configDir(), "config.json");
}

function ensureDir(): void {
  const dir = configDir();
  if (!existsSync(dir)) {
    mkdirSync(dir, { recursive: true, mode: 0o700 });
  }
}

export function loadCredentials(): Credentials | null {
  const path = credentialsPath();
  if (!existsSync(path)) return null;
  try {
    return JSON.parse(readFileSync(path, "utf-8")) as Credentials;
  } catch {
    return null;
  }
}

export function saveCredentials(creds: Credentials): void {
  ensureDir();
  // 0600 — the refresh token is a bearer credential for this device.
  writeFileSync(credentialsPath(), JSON.stringify(creds, null, 2), {
    mode: 0o600,
  });
}

export function clearCredentials(): void {
  const path = credentialsPath();
  if (existsSync(path)) {
    writeFileSync(path, "{}", { mode: 0o600 });
  }
}

export function loadConfig(): BridgeConfig {
  const path = configPath();
  if (!existsSync(path)) return { servers: [] };
  try {
    const parsed = JSON.parse(readFileSync(path, "utf-8")) as BridgeConfig;
    return { servers: parsed.servers ?? [] };
  } catch {
    return { servers: [] };
  }
}

function saveConfig(config: BridgeConfig): void {
  ensureDir();
  writeFileSync(configPath(), JSON.stringify(config, null, 2), { mode: 0o600 });
}

export function upsertServer(server: ServerConfig): void {
  if (server.type === "url") assertLoopbackUrl(server.url);
  const config = loadConfig();
  const idx = config.servers.findIndex((s) => s.key === server.key);
  if (idx >= 0) config.servers[idx] = server;
  else config.servers.push(server);
  saveConfig(config);
}

export function removeServer(key: string): boolean {
  const config = loadConfig();
  const before = config.servers.length;
  config.servers = config.servers.filter((s) => s.key !== key);
  saveConfig(config);
  return config.servers.length < before;
}

/** Expand a leading ~ so quoted paths like "~/Documents" still resolve to $HOME. */
export function expandTilde(p: string): string {
  if (p === "~") return homedir();
  if (p.startsWith("~/")) return join(homedir(), p.slice(2));
  return p;
}

/** The built-in filesystem server config — one canonical shape for both the
 * `gaia bridge fs` command and the `gaia bridge add` wizard. */
export function filesystemServer(
  allow: string[],
  allowWrite: boolean,
): FilesystemServer {
  return {
    type: "filesystem",
    key: FILESYSTEM_SERVER_KEY,
    name: "Local Files",
    allow,
    allowWrite,
  };
}

export function getFilesystemServer(): FilesystemServer | undefined {
  return loadConfig().servers.find(
    (s): s is FilesystemServer =>
      s.type === "filesystem" && s.key === FILESYSTEM_SERVER_KEY,
  );
}

export function apiUrlFromEnvOrCreds(explicit?: string): string {
  if (explicit) return explicit.replace(/\/$/, "");
  const creds = loadCredentials();
  if (creds?.apiUrl) return creds.apiUrl.replace(/\/$/, "");
  return (process.env["GAIA_API_URL"] ?? DEFAULT_API_URL).replace(/\/$/, "");
}

// Persistent state on the user's machine: credentials (secret, 0600) and the
// list of MCP servers this device exposes. Lives under ~/.gaia/bridge/.

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import type {
  Credentials,
  FilesystemServer,
  ServerConfig,
} from "./config.types.js";
import { DEFAULT_API_URL, FILESYSTEM_SERVER_KEY } from "./constants.js";

interface BridgeConfig {
  servers: ServerConfig[];
}

const CONFIG_DIR = join(homedir(), ".gaia", "bridge");
const CREDENTIALS_PATH = join(CONFIG_DIR, "credentials.json");
const CONFIG_PATH = join(CONFIG_DIR, "config.json");

function ensureDir(): void {
  if (!existsSync(CONFIG_DIR)) {
    mkdirSync(CONFIG_DIR, { recursive: true, mode: 0o700 });
  }
}

export function loadCredentials(): Credentials | null {
  if (!existsSync(CREDENTIALS_PATH)) return null;
  try {
    return JSON.parse(readFileSync(CREDENTIALS_PATH, "utf-8")) as Credentials;
  } catch {
    return null;
  }
}

export function saveCredentials(creds: Credentials): void {
  ensureDir();
  // 0600 — the refresh token is a bearer credential for this device.
  writeFileSync(CREDENTIALS_PATH, JSON.stringify(creds, null, 2), {
    mode: 0o600,
  });
}

export function clearCredentials(): void {
  if (existsSync(CREDENTIALS_PATH)) {
    writeFileSync(CREDENTIALS_PATH, "{}", { mode: 0o600 });
  }
}

export function loadConfig(): BridgeConfig {
  if (!existsSync(CONFIG_PATH)) return { servers: [] };
  try {
    const parsed = JSON.parse(
      readFileSync(CONFIG_PATH, "utf-8"),
    ) as BridgeConfig;
    return { servers: parsed.servers ?? [] };
  } catch {
    return { servers: [] };
  }
}

function saveConfig(config: BridgeConfig): void {
  ensureDir();
  writeFileSync(CONFIG_PATH, JSON.stringify(config, null, 2), { mode: 0o600 });
}

export function upsertServer(server: ServerConfig): void {
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

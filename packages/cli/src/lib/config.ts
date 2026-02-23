import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import { CLI_VERSION } from "./version.js";

export const GAIA_CONFIG_DIR = path.join(os.homedir(), ".gaia");
export const CONFIG_PATH = path.join(GAIA_CONFIG_DIR, "config.json");

export interface GaiaConfig {
  version: string;
  setupComplete: boolean;
  setupMethod: "manual" | "infisical";
  repoPath: string;
  createdAt: string;
  updatedAt: string;
}

function ensureConfigDir(): void {
  if (!fs.existsSync(GAIA_CONFIG_DIR)) {
    fs.mkdirSync(GAIA_CONFIG_DIR, { recursive: true });
  }
}

export function readConfig(): GaiaConfig | null {
  try {
    if (!fs.existsSync(CONFIG_PATH)) return null;
    const raw = fs.readFileSync(CONFIG_PATH, "utf-8");
    return JSON.parse(raw) as GaiaConfig;
  } catch {
    return null;
  }
}

export function writeConfig(config: GaiaConfig): void {
  ensureConfigDir();
  fs.writeFileSync(CONFIG_PATH, `${JSON.stringify(config, null, 2)}\n`);
}

export function updateConfig(partial: Partial<GaiaConfig>): void {
  const existing = readConfig();
  const updated: GaiaConfig = {
    ...(existing ?? {
      version: CLI_VERSION,
      setupComplete: false,
      setupMethod: "manual",
      repoPath: "",
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    }),
    ...partial,
    updatedAt: new Date().toISOString(),
  };
  writeConfig(updated);
}

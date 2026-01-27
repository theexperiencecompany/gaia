import * as dotenv from "dotenv";
import * as path from "path";
import type { BotConfig } from "../types";

let envLoaded = false;

function ensureEnvLoaded() {
  if (envLoaded) return;
  // Load in reverse priority order (later loads override earlier)
  dotenv.config({ path: path.resolve(process.cwd(), "../../.env") });
  dotenv.config({ path: path.resolve(process.cwd(), "../.env") });
  dotenv.config();
  envLoaded = true;
}

export function loadConfig(): BotConfig {
  ensureEnvLoaded();
  const gaiaApiUrl = process.env.GAIA_API_URL;
  const gaiaApiKey = process.env.GAIA_BOT_API_KEY;
  const gaiaWebUrl = process.env.GAIA_WEB_URL || "https://heygaia.io";

  if (!gaiaApiUrl) {
    throw new Error("GAIA_API_URL is required");
  }
  if (!gaiaApiKey) {
    throw new Error("GAIA_BOT_API_KEY is required");
  }

  return { gaiaApiUrl, gaiaApiKey, gaiaWebUrl };
}

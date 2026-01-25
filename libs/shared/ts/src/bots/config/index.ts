import * as dotenv from "dotenv";
import * as path from "path";
import type { BotConfig } from "../types";

// Look for .env in apps/bots directory (shared across all bots)
dotenv.config({ path: path.resolve(process.cwd(), "../.env") });
// Also check current directory for bot-specific overrides
dotenv.config();

/**
 * Loads and validates the bot configuration from environment variables.
 *
 * @returns The validated BotConfig object containing API URL and key.
 * @throws Error if any required environment variable is missing.
 */
export function loadConfig(): BotConfig {
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

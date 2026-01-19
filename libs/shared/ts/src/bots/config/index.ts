import type { BotConfig } from "../types";
import * as dotenv from "dotenv";

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

  if (!gaiaApiUrl) {
    throw new Error("GAIA_API_URL is required");
  }
  if (!gaiaApiKey) {
    throw new Error("GAIA_BOT_API_KEY is required");
  }

  return { gaiaApiUrl, gaiaApiKey };
}

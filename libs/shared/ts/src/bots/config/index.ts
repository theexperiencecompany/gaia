import * as fs from "node:fs";
import * as path from "node:path";
import * as dotenv from "dotenv";
import type { BotConfig } from "../types";
import { wideLog } from "../utils/wide-events";
import { injectInfisicalSecrets } from "./secrets";

export { injectInfisicalSecrets } from "./secrets";

/**
 * Loads and validates the bot configuration from environment variables.
 *
 * Resolution order (first value wins): existing process env vars (Docker/CI) →
 * `apps/bots/.env` (shared) → `<bot>/.env` in cwd (legacy/Docker fallback) →
 * Infisical remote secrets (fills remaining gaps).
 *
 * @throws Error listing which required vars are still missing after all sources are checked.
 */
export async function loadConfig(): Promise<BotConfig> {
  // Runs inside boot()'s `bot_boot` boundary, so which env sources answered —
  // and every optional key that did not — lands on that one event instead of
  // being scattered across half a dozen start-up lines nobody correlates.

  // 1. Shared .env — apps/bots/.env (cwd is apps/bots/<platform>)
  const sharedEnvPath = path.resolve(process.cwd(), "..", ".env");
  const sharedEnvFound = fs.existsSync(sharedEnvPath);
  if (sharedEnvFound) {
    dotenv.config({ path: sharedEnvPath });
  } else {
    wideLog.warning("env_file_missing", { path: sharedEnvPath });
  }

  // 2. Local .env in cwd — Docker / standalone fallback
  const localEnvPath = path.resolve(process.cwd(), ".env");
  const localEnvFound = fs.existsSync(localEnvPath);
  if (localEnvFound) {
    dotenv.config({ path: localEnvPath });
  }
  wideLog.setNs("config", {
    shared_env: sharedEnvFound,
    local_env: localEnvFound,
  });

  // 3. Infisical — fills any vars not already set
  await injectInfisicalSecrets();

  // 4. Validate required config
  const gaiaApiUrl = process.env.GAIA_API_URL;
  const gaiaApiKey = process.env.GAIA_BOT_API_KEY;
  const gaiaFrontendUrl = process.env.GAIA_FRONTEND_URL;
  const botLogHashSecret = process.env.BOT_LOG_HASH_SECRET;

  const missing: string[] = [];
  if (!gaiaApiUrl) missing.push("GAIA_API_URL");
  if (!gaiaApiKey) missing.push("GAIA_BOT_API_KEY");
  if (!gaiaFrontendUrl) missing.push("GAIA_FRONTEND_URL");
  if (!botLogHashSecret) missing.push("BOT_LOG_HASH_SECRET");

  if (missing.length > 0) {
    throw new Error(
      `Missing required config: ${missing.join(", ")}. ` +
        "Set them in apps/bots/.env or configure Infisical. " +
        "Generate BOT_LOG_HASH_SECRET with: openssl rand -hex 32",
    );
  }

  // HMAC-SHA256 key for hashing PII (phone numbers, platform user IDs) in logs. RFC 2104
  // recommends a key >= the hash output size (32 bytes/256 bits); since we document hex-encoded
  // keys, that's 64 chars (a 32-char hex value is only 16 bytes, below the RFC floor).
  if (botLogHashSecret!.length < 64) {
    throw new Error(
      "BOT_LOG_HASH_SECRET must be at least 64 characters (32 bytes / 256 bits). " +
        "Generate one with: openssl rand -hex 32",
    );
  }

  const posthogApiKey = process.env.POSTHOG_API_KEY;
  if (!posthogApiKey) {
    wideLog.warning("config_optional_missing", {
      key: "POSTHOG_API_KEY",
      effect: "bot_analytics_disabled",
    });
  }

  const rabbitmqUrl = process.env.RABBITMQ_URL;
  if (!rabbitmqUrl) {
    wideLog.warning("config_optional_missing", {
      key: "RABBITMQ_URL",
      effect: "outbound_consumer_disabled",
    });
  }

  return {
    gaiaApiUrl: gaiaApiUrl!,
    gaiaApiKey: gaiaApiKey!,
    gaiaFrontendUrl: gaiaFrontendUrl!,
    posthogApiKey,
    rabbitmqUrl,
  };
}

import * as fs from "node:fs";
import * as path from "node:path";
import * as dotenv from "dotenv";
import type { BotConfig } from "../types";
import { injectInfisicalSecrets } from "./secrets";

export { injectInfisicalSecrets } from "./secrets";

const log = (msg: string) => console.log(`[config] ${msg}`);
const warn = (msg: string) => console.warn(`[config] ${msg}`);

/**
 * Loads and validates the bot configuration from environment variables.
 *
 * Resolution order (first value wins):
 * 1. Existing process env vars (e.g. from Docker / CI)
 * 2. `apps/bots/.env` (shared file, one level up from bot cwd)
 * 3. `<bot>/.env` in cwd (legacy / Docker fallback)
 * 4. Infisical remote secrets (fills remaining gaps)
 *
 * @returns The validated BotConfig object.
 * @throws Error if required env vars are missing after all sources are checked.
 */
export async function loadConfig(): Promise<BotConfig> {
  // 1. Shared .env — apps/bots/.env (cwd is apps/bots/<platform>)
  const sharedEnvPath = path.resolve(process.cwd(), "..", ".env");
  if (fs.existsSync(sharedEnvPath)) {
    dotenv.config({ path: sharedEnvPath });
    log(`Loaded shared env from ${sharedEnvPath}`);
  } else {
    warn(`No shared .env found at ${sharedEnvPath}`);
  }

  // 2. Local .env in cwd — Docker / standalone fallback
  const localEnvPath = path.resolve(process.cwd(), ".env");
  if (fs.existsSync(localEnvPath)) {
    dotenv.config({ path: localEnvPath });
    log(`Loaded local env from ${localEnvPath}`);
  }

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

  // BOT_LOG_HASH_SECRET is the HMAC-SHA256 key used to hash PII (phone numbers,
  // platform user IDs) in logs. RFC 2104 recommends a key of at least the hash
  // output size (32 bytes / 256 bits) to prevent brute-force recovery of hashed
  // identifiers. We document hex-encoded keys, so enforce 64 characters
  // (= 32 bytes when hex-decoded). A 32-char hex value would only be 16 bytes
  // and falls below the RFC 2104 floor.
  if (botLogHashSecret!.length < 64) {
    throw new Error(
      "BOT_LOG_HASH_SECRET must be at least 64 characters (32 bytes / 256 bits). " +
        "Generate one with: openssl rand -hex 32",
    );
  }

  const posthogApiKey = process.env.POSTHOG_API_KEY;
  if (!posthogApiKey) {
    warn("POSTHOG_API_KEY not set — bot analytics will be disabled");
  }

  const rabbitmqUrl = process.env.RABBITMQ_URL;
  if (!rabbitmqUrl) {
    warn("RABBITMQ_URL not set — outbound message consumer will be disabled");
  }

  log("Configuration loaded successfully");
  return {
    gaiaApiUrl: gaiaApiUrl!,
    gaiaApiKey: gaiaApiKey!,
    gaiaFrontendUrl: gaiaFrontendUrl!,
    posthogApiKey,
    rabbitmqUrl,
  };
}

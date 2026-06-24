/**
 * Infisical secrets management for GAIA bots.
 *
 * Resolution:
 * - If all 4 Infisical env vars are set → fetch remote secrets
 * - If partially set → warn about incomplete config
 * - If none set in dev → skip (using local .env only)
 * - If none set in prod → throw (Infisical is required in production)
 *
 * Local environment variables always take precedence over Infisical secrets.
 */

import { InfisicalSDK } from "@infisical/sdk";
import { createBotLogger } from "../utils/logger";

const logger = createBotLogger("shared", "secrets");

class InfisicalConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InfisicalConfigError";
  }
}

const INFISICAL_VARS = [
  "INFISICAL_TOKEN",
  "INFISICAL_PROJECT_ID",
  "INFISICAL_MACHINE_IDENTITY_CLIENT_ID",
  "INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET",
] as const;

export async function injectInfisicalSecrets(): Promise<void> {
  const env =
    process.env.NODE_ENV === "production" ? "production" : "development";
  const isProduction = env === "production";

  const present = INFISICAL_VARS.filter((k) => !!process.env[k]);
  const missing = INFISICAL_VARS.filter((k) => !process.env[k]);

  // No Infisical vars at all
  if (present.length === 0) {
    if (isProduction) {
      throw new InfisicalConfigError(
        "Infisical is required in production. " +
          `Missing: ${INFISICAL_VARS.join(", ")}`,
      );
    }
    logger.info("infisical_skipped", { reason: "no_config_vars_set" });
    return;
  }

  // Partially configured — always an error
  if (missing.length > 0) {
    const msg =
      `Incomplete Infisical config: missing ${missing.join(", ")} ` +
      `(found ${present.join(", ")})`;
    if (isProduction) {
      throw new InfisicalConfigError(msg);
    }
    logger.warn("infisical_config_incomplete", {
      missing: missing,
      present: present,
    });
    return;
  }

  // All vars present — fetch secrets
  const clientId = process.env.INFISICAL_MACHINE_IDENTITY_CLIENT_ID!;
  const clientSecret = process.env.INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET!;
  const projectId = process.env.INFISICAL_PROJECT_ID!;

  try {
    const start = Date.now();
    logger.info("infisical_connecting");

    const client = new InfisicalSDK({
      siteUrl: "https://app.infisical.com",
    });
    await client.auth().universalAuth.login({ clientId, clientSecret });
    logger.info("infisical_authenticated", { duration_ms: Date.now() - start });

    const secretsStart = Date.now();
    const result = await client.secrets().listSecrets({
      projectId,
      environment: env,
      secretPath: "/",
      expandSecretReferences: true,
      includeImports: true,
    });

    let injected = 0;
    let skipped = 0;
    for (const secret of result.secrets) {
      if (process.env[secret.secretKey] === undefined) {
        process.env[secret.secretKey] = secret.secretValue;
        injected++;
      } else {
        skipped++;
      }
    }

    logger.info("infisical_secrets_loaded", {
      total: result.secrets.length,
      injected,
      skipped,
      duration_ms: Date.now() - secretsStart,
    });
  } catch (error) {
    if (error instanceof InfisicalConfigError) throw error;
    throw new InfisicalConfigError(
      `Failed to fetch secrets from Infisical: ${error}`,
    );
  }
}

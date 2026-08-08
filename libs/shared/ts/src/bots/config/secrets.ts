/**
 * Infisical secrets management for GAIA bots.
 *
 * Resolution:
 * - If all Infisical env vars are set → fetch remote secrets
 * - If partially set → warn about incomplete config
 * - If none set in dev → skip (using local .env only)
 * - If none set in prod → throw (Infisical is required in production)
 *
 * Local environment variables always take precedence over Infisical secrets.
 */

import { InfisicalSDK } from "@infisical/sdk";
import { wideLog } from "../utils/wide-events";

class InfisicalConfigError extends Error {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = "InfisicalConfigError";
  }
}

const INFISICAL_VARS = [
  "INFISICAL_PROJECT_ID",
  "INFISICAL_MACHINE_IDENTITY_CLIENT_ID",
  "INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET",
] as const;

export async function injectInfisicalSecrets(): Promise<void> {
  // ENV doubles as the Infisical environment slug (development/staging/
  // production). Unlike the Python loader — which defaults an absent ENV to
  // production — a bare bot checkout resolves to development, because
  // apps/bots/.env.example has never required ENV and defaulting to production
  // would break every existing local setup on the next pull.
  //
  // Deployment never relies on that fallback: apps/bots/Dockerfile bakes
  // ENV=production into the image and docker-compose.prod.yml sets it again per
  // service, so a container can only ever resolve production. NODE_ENV is kept
  // as a third layer for images built outside this Dockerfile.
  const env =
    process.env.ENV ??
    (process.env.NODE_ENV === "production" ? "production" : "development");
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
    wideLog.setNs("infisical", { skipped: "no_config_vars_set" });
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
    wideLog.warning("infisical_config_incomplete", {
      missing,
      present,
    });
    return;
  }

  // All vars present — fetch secrets
  const clientId = process.env.INFISICAL_MACHINE_IDENTITY_CLIENT_ID!;
  const clientSecret = process.env.INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET!;
  const projectId = process.env.INFISICAL_PROJECT_ID!;

  try {
    const start = Date.now();
    const client = new InfisicalSDK({
      siteUrl: "https://app.infisical.com",
    });
    await client.auth().universalAuth.login({ clientId, clientSecret });
    wideLog.setNs("infisical", { auth_ms: Date.now() - start });

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

    wideLog.setNs("infisical", {
      total: result.secrets.length,
      injected,
      skipped,
      fetch_ms: Date.now() - secretsStart,
    });
  } catch (error) {
    if (error instanceof InfisicalConfigError) throw error;
    // `cause` keeps the original failure's type and message alive for the log
    // sink; interpolating it into the message destroys both.
    throw new InfisicalConfigError("infisical_fetch_failed", { cause: error });
  }
}

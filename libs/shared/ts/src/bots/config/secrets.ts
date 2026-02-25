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

const log = (msg: string) => console.log(`[secrets] ${msg}`);
const warn = (msg: string) => console.warn(`[secrets] ${msg}`);

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
    log("No Infisical config found, using local .env only");
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
    warn(msg);
    return;
  }

  // All vars present — fetch secrets
  const clientId = process.env.INFISICAL_MACHINE_IDENTITY_CLIENT_ID!;
  const clientSecret = process.env.INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET!;
  const projectId = process.env.INFISICAL_PROJECT_ID!;

  try {
    const start = Date.now();
    log("Connecting to Infisical...");

    const client = new InfisicalSDK({
      siteUrl: "https://app.infisical.com",
    });
    await client.auth().universalAuth.login({ clientId, clientSecret });
    log(`Authenticated in ${Date.now() - start}ms`);

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

    log(
      `Fetched ${result.secrets.length} secrets in ${Date.now() - secretsStart}ms ` +
        `(${injected} injected, ${skipped} skipped — local env takes precedence)`,
    );
  } catch (error) {
    if (error instanceof InfisicalConfigError) throw error;
    throw new InfisicalConfigError(
      `Failed to fetch secrets from Infisical: ${error}`,
    );
  }
}

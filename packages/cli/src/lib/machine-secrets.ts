/**
 * Machine-local secrets for self-hosted instances.
 *
 * A self-host install must boot with AGENT_SECRET / BOT_SESSION_TOKEN_SECRET /
 * EMAIL_UNSUBSCRIBE_SECRET set, file sharing needs SHARE_GRANT_SECRET and the
 * chat bots authenticate with GAIA_BOT_API_KEY, but
 * asking users to invent random strings is hostile UX. The CLI generates them once (crypto.randomBytes,
 * hex-encoded, openssl-rand-hex-32 equivalent) and merges them into
 * apps/api/.env with merge-don't-clobber semantics: values already present in
 * an existing .env are kept untouched, only missing ones are generated.
 *
 * INSTANCE_SECRET (the key that encrypts stored provider credentials) is
 * generated on a fresh install only: an install that already has a .env may
 * have encrypted credentials under a database-held secret, and a new env value
 * would override it and make them unreadable.
 * @module lib/machine-secrets
 */

import * as crypto from "node:crypto";
import { parseEnvFileValues } from "./env-writer.js";

/** Env vars the CLI owns generating for self-host installs. */
const MACHINE_SECRET_VARS = [
  "AGENT_SECRET",
  "BOT_SESSION_TOKEN_SECRET",
  "EMAIL_UNSUBSCRIBE_SECRET",
  "SHARE_GRANT_SECRET",
  "GAIA_BOT_API_KEY",
] as const;

/** Keeps the credential-encryption key out of the database it protects. */
const FRESH_INSTALL_SECRET_VARS = ["INSTANCE_SECRET"] as const;

/** Generate one machine secret (64 hex chars, ~openssl rand -hex 32). */
export function generateMachineSecret(): string {
  return crypto.randomBytes(32).toString("hex");
}

/**
 * Extract the set of variable names that already have a non-empty value in a
 * raw `.env` file body. Blank values count as missing so a half-written file
 * gets completed instead of trusted. (Delegates to the canonical parser.)
 */
export function parseAssignedEnvKeys(content: string | null): Set<string> {
  return new Set(Object.keys(parseEnvFileValues(content)));
}

/**
 * Compute the machine-secret values to write for an install.
 *
 * Merge-don't-clobber: secrets already assigned in `existingEnvContent` are
 * preserved verbatim (regenerating would invalidate sessions/tokens signed
 * with them); only the missing ones are freshly generated. On a fresh
 * install (no existing .env) every secret is generated.
 */
export function collectMachineSecrets(
  existingEnvContent: string | null,
): Record<string, string> {
  const assigned = parseAssignedEnvKeys(existingEnvContent);
  const secrets: Record<string, string> = {};
  const names =
    existingEnvContent === null
      ? [...MACHINE_SECRET_VARS, ...FRESH_INSTALL_SECRET_VARS]
      : MACHINE_SECRET_VARS;
  for (const name of names) {
    if (!assigned.has(name)) {
      secrets[name] = generateMachineSecret();
    }
  }
  return secrets;
}

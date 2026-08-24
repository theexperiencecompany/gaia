/**
 * Machine-local secrets for self-hosted instances.
 *
 * A self-host install must boot with AGENT_SECRET / BOT_SESSION_TOKEN_SECRET /
 * EMAIL_UNSUBSCRIBE_SECRET set, but asking users to invent three random
 * strings is hostile UX. The CLI generates them once (crypto.randomBytes,
 * hex-encoded, openssl-rand-hex-32 equivalent) and merges them into
 * apps/api/.env with merge-don't-clobber semantics: values already present in
 * an existing .env are kept untouched, only missing ones are generated.
 * @module lib/machine-secrets
 */

import * as crypto from "node:crypto";
import { parseEnvFileValues } from "./env-writer.js";

/** Env vars the CLI owns generating for self-host installs. */
const MACHINE_SECRET_VARS = [
  "AGENT_SECRET",
  "BOT_SESSION_TOKEN_SECRET",
  "EMAIL_UNSUBSCRIBE_SECRET",
] as const;

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
  for (const name of MACHINE_SECRET_VARS) {
    if (!assigned.has(name)) {
      secrets[name] = generateMachineSecret();
    }
  }
  return secrets;
}

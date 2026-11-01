/**
 * Which GAIA installation a command acts on, and what kind it is: a source
 * checkout or a release's setup files, self-host or developer.
 * @module lib/install-root
 */

import * as fs from "fs";
import * as path from "path";
import { readConfig, updateConfig } from "./config.js";
import type { SetupMode } from "./env-parser.js";
import { detectSetupMode } from "./env-writer.js";
import { apiEnvPath, homeRelative } from "./paths.js";
import { BUNDLE_MANIFEST } from "./selfhost-bundle.js";

export { detectSetupMode } from "./env-writer.js";
export { apiEnvPath } from "./paths.js";

/** The file whose presence marks a directory as a GAIA checkout. */
const CHECKOUT_MARKER = "apps/api/app/config/settings_validator.py";

/** A source checkout: what the developer commands (init, setup, dev) need. */
export function isGaiaCheckout(dir: string): boolean {
  return fs.existsSync(path.join(dir, CHECKOUT_MARKER));
}

/** @throws Error when the install holds only a release's setup files, which cannot be built. */
export function assertBuildableInstall(repoPath: string): void {
  if (isGaiaCheckout(repoPath)) return;
  throw new Error(
    `Building GAIA needs its source, and ${homeRelative(repoPath)} holds only a release's setup files.\n` +
      "Get the source with 'gaia init', then build there.",
  );
}

/** A self-host install: a release's setup files (the bundle) or a source checkout. */
export function isGaiaInstall(dir: string): boolean {
  return fs.existsSync(path.join(dir, BUNDLE_MANIFEST)) || isGaiaCheckout(dir);
}

/**
 * True when the CLI may (re)write this install as self-host: it is one, or it
 * has no apps/api/.env yet. A developer's .env, or one that names no mode, is never touched.
 */
export async function isSelfhostOrUnconfigured(dir: string): Promise<boolean> {
  if (!fs.existsSync(apiEnvPath(dir))) return true;
  return (await detectSetupMode(dir)) === "selfhost";
}

/** The nearest directory at or above startDir that matches. */
function findAbove(
  startDir: string,
  matches: (dir: string) => boolean,
): string | null {
  let currentDir = startDir;
  while (currentDir !== path.dirname(currentDir)) {
    if (matches(currentDir)) return currentDir;
    currentDir = path.dirname(currentDir);
  }
  return null;
}

/** The install recorded in ~/.gaia/config.json; a record that names no install is reset. */
function findRecordedInstall(): string | null {
  const config = readConfig();
  if (!config?.repoPath) return null;
  if (isGaiaInstall(config.repoPath)) return config.repoPath;
  console.warn(
    `Warning: Saved repo path "${config.repoPath}" is no longer a valid GAIA installation. Resetting config.`,
  );
  updateConfig({ repoPath: "", setupComplete: false });
  return null;
}

/** The source checkout to configure: the one at or above cwd, else the recorded install if it is one. */
export function findRepoRoot(startDir?: string): string | null {
  const local = findAbove(startDir ?? process.cwd(), isGaiaCheckout);
  if (local) return local;
  const recorded = findRecordedInstall();
  return recorded && isGaiaCheckout(recorded) ? recorded : null;
}

/**
 * The installation to inspect or run: a configured install at or above cwd,
 * else the recorded install. An unconfigured checkout (a source clone) never
 * shadows the install `gaia up` recorded.
 */
export function findInstallRoot(startDir?: string): string | null {
  const local = findAbove(startDir ?? process.cwd(), isGaiaInstall);
  if (local && fs.existsSync(apiEnvPath(local))) return local;
  return findRecordedInstall() ?? local;
}

/** "path (mode)": which installation a command is inspecting. */
export function describeInstall(
  repoPath: string | null,
  mode: SetupMode | null,
): string {
  if (!repoPath) return "GAIA isn't installed yet";
  const shown = homeRelative(repoPath);
  if (mode)
    return `${shown} (${mode === "selfhost" ? "self-host" : "developer"})`;
  return fs.existsSync(apiEnvPath(repoPath))
    ? `${shown} (setup mode unknown: apps/api/.env has no SETUP_MODE)`
    : `${shown} (not set up yet: no apps/api/.env)`;
}

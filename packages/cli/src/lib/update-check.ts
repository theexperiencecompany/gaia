/**
 * Is there a newer GAIA release this computer can install? The answer is
 * cached in ~/.gaia so a header or doctor never waits on the network twice a
 * day; the check itself is time-boxed and a failure only logs.
 * @module lib/update-check
 */

import * as fs from "node:fs";
import * as path from "node:path";
import semver from "semver";
import { GAIA_CONFIG_DIR } from "./config.js";
import { dockerArch, findReleaseImageGap } from "./image-availability.js";
import { GAIA_LOG_DIR } from "./logs.js";

const NPM_LATEST_URL = "https://registry.npmjs.org/@heygaia/cli/latest";
const CACHE_PATH = path.join(GAIA_CONFIG_DIR, "update-check.json");
const LOG_PATH = path.join(GAIA_LOG_DIR, "update-check.log");
const CACHE_TTL_MS = 24 * 60 * 60 * 1000;
const NPM_TIMEOUT_MS = 5_000;

interface UpdateCheckCache {
  checkedAt: string;
  arch: string;
  /** The newest stable release with images for `arch`, e.g. "v0.7.0"; null when none. */
  latest: string | null;
}

/** A GAIA release image tag (v<semver>) as a version, or null for latest / a commit sha. */
export function releaseVersion(tag: string): semver.SemVer | null {
  return /^v\d/.test(tag) ? semver.parse(tag.slice(1)) : null;
}

/** True when `candidate` is a release newer than the release `current`. */
export function isNewerRelease(candidate: string, current: string): boolean {
  const next = releaseVersion(candidate);
  const now = releaseVersion(current);
  return next !== null && now !== null && semver.gt(next, now);
}

function readCache(): UpdateCheckCache | null {
  if (!fs.existsSync(CACHE_PATH)) return null;
  const cache = JSON.parse(
    fs.readFileSync(CACHE_PATH, "utf-8"),
  ) as UpdateCheckCache;
  return cache.arch === dockerArch() ? cache : null;
}

/** Ask npm for the newest stable CLI, then GHCR whether its images exist for this CPU. */
async function fetchLatestInstallableRelease(): Promise<string | null> {
  const res = await fetch(NPM_LATEST_URL, {
    signal: AbortSignal.timeout(NPM_TIMEOUT_MS),
  });
  if (!res.ok) throw new Error(`npm answered HTTP ${res.status}`);
  const { version } = (await res.json()) as { version: string };
  const tag = `v${version}`;
  return (await findReleaseImageGap(tag)) === null ? tag : null;
}

function logFailure(error: unknown): void {
  fs.mkdirSync(GAIA_LOG_DIR, { recursive: true });
  fs.appendFileSync(
    LOG_PATH,
    `${new Date().toISOString()} update check failed: ${(error as Error).message}\n`,
  );
}

/**
 * Refresh the cached answer when it is a day old. A network failure is logged
 * to ~/.gaia/logs/update-check.log and the previous answer stays.
 */
export async function refreshLatestRelease(): Promise<string | null> {
  const cache = readCache();
  if (cache && Date.now() - Date.parse(cache.checkedAt) < CACHE_TTL_MS) {
    return cache.latest;
  }
  try {
    const latest = await fetchLatestInstallableRelease();
    fs.mkdirSync(GAIA_CONFIG_DIR, { recursive: true });
    const fresh: UpdateCheckCache = {
      checkedAt: new Date().toISOString(),
      arch: dockerArch(),
      latest,
    };
    fs.writeFileSync(CACHE_PATH, JSON.stringify(fresh));
    return latest;
  } catch (error) {
    // The only check allowed to fail quietly: it must never break the command it decorates.
    logFailure(error);
    return cache?.latest ?? null;
  }
}

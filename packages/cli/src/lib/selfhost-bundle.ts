/**
 * The self-host bundle: the few files a release's stack reads from disk (its
 * compose files and Caddyfile), published as gaia-selfhost-<version>.tar.gz
 * on the cli-v<version> GitHub Release by scripts/ci/release.sh
 * selfhost-bundle. `gaia up` unpacks it into the install and `gaia update`
 * swaps it for the next release's, so a self-host install never needs git.
 * Everything else in the install (the .env files, backups) is the user's and
 * is never touched.
 * @module lib/selfhost-bundle
 */

import * as fs from "node:fs";
import * as fsp from "node:fs/promises";
import * as path from "node:path";
import { execa } from "execa";
import { z } from "zod";
import {
  assertDigest,
  DownloadError,
  type DownloadProgress,
  digestForAsset,
  downloadBytes,
} from "./download.js";
import { GAIA_VERSION_ENV_KEY } from "./env-writer.js";
import {
  currentSelfhostDir,
  LEGACY_SELFHOST_DIR,
  SELFHOST_COMPOSE_FILE,
} from "./paths.js";
import { releaseGitTag } from "./release.js";
import { releaseImageTag } from "./version.js";

/** The bundle's own record of its release and the files it owns, at the install root. */
export const BUNDLE_MANIFEST = "gaia-selfhost.json";

/** Overrides where the bundle assets are read from, for testing a build that is not released. */
const BUNDLE_BASE_URL_ENV = "GAIA_BUNDLE_BASE_URL";

const RELEASE_BASE =
  "https://github.com/theexperiencecompany/gaia/releases/download";

const HTTP_NOT_FOUND = 404;

const ManifestSchema = z.object({
  version: z.string(),
  files: z.array(z.string()),
});

export type BundleManifest = z.infer<typeof ManifestSchema>;

/**
 * One plain line per override of where this run's release comes from, so a
 * test build never passes for a published one; empty for a normal run.
 */
export function releaseSourceNotes(
  env: NodeJS.ProcessEnv,
  cliVersion: string,
): string[] {
  const notes: string[] = [];
  const imageTag = releaseImageTag(env, cliVersion);
  if (imageTag !== `v${cliVersion}`) {
    notes.push(
      `Installing GAIA ${imageTag}'s images, not v${cliVersion}'s (${GAIA_VERSION_ENV_KEY})`,
    );
  }
  const base = env[BUNDLE_BASE_URL_ENV];
  if (base) {
    notes.push(`Setup files from ${base} (${BUNDLE_BASE_URL_ENV})`);
  }
  return notes;
}

/** Where a release's bundle and its sha256sum file live. */
export function bundleAssetUrls(
  imageTag: string,
  env: NodeJS.ProcessEnv = process.env,
): { asset: string; bundle: string; checksum: string } {
  const gitTag = releaseGitTag(imageTag);
  const asset = `gaia-selfhost-${imageTag.slice(1)}.tar.gz`;
  const base = (
    env[BUNDLE_BASE_URL_ENV] ?? `${RELEASE_BASE}/${gitTag}`
  ).replace(/\/+$/, "");
  return {
    asset,
    bundle: `${base}/${asset}`,
    checksum: `${base}/${asset}.sha256`,
  };
}

/**
 * Download a release's bundle and prove it is the published one.
 * @throws Error when the release has no bundle or its bytes do not match the checksum.
 */
export async function fetchBundle(
  imageTag: string,
  onProgress: (progress: DownloadProgress) => void,
): Promise<Buffer> {
  const { asset, bundle, checksum } = bundleAssetUrls(imageTag);
  try {
    const sums = (await downloadBytes(checksum)).toString("utf-8");
    const expected = digestForAsset(sums, asset, checksum);
    const bytes = await downloadBytes(bundle, onProgress);
    assertDigest(bytes, expected, asset);
    return bytes;
  } catch (error) {
    if (error instanceof DownloadError && error.status === HTTP_NOT_FOUND) {
      throw new Error(
        `GAIA ${imageTag} has no published setup files: ${error.url} answered 404.`,
      );
    }
    throw error;
  }
}

/** The bundle manifest of an install; null when the install is not a bundle install. */
export function readBundleManifest(dir: string): BundleManifest | null {
  const file = path.join(dir, BUNDLE_MANIFEST);
  if (!fs.existsSync(file)) return null;
  return ManifestSchema.parse(JSON.parse(fs.readFileSync(file, "utf-8")));
}

/**
 * Unpack a verified bundle into an empty staging directory.
 * @throws Error when the bundle is for another release or misses a file it lists.
 */
export async function unpackBundle(
  archive: Buffer,
  stagingDir: string,
  imageTag: string,
): Promise<BundleManifest> {
  await fsp.rm(stagingDir, { recursive: true, force: true });
  await fsp.mkdir(stagingDir, { recursive: true });
  await execa("tar", ["-xzf", "-", "-C", stagingDir], { input: archive });
  const manifest = readBundleManifest(stagingDir);
  if (!manifest) {
    throw new Error(`The setup files for GAIA ${imageTag} have no manifest.`);
  }
  if (manifest.version !== imageTag) {
    throw new Error(
      `The setup files downloaded for GAIA ${imageTag} are for GAIA ${manifest.version}, not ${imageTag}.`,
    );
  }
  const missing = manifest.files.filter(
    (file) => !fs.existsSync(path.join(stagingDir, file)),
  );
  if (missing.length > 0) {
    throw new Error(
      `The setup files for GAIA ${imageTag} are missing ${missing.join(", ")}.`,
    );
  }
  return manifest;
}

/** Remove now-empty directories from dir up to (not including) root. */
async function pruneEmptyParents(root: string, dir: string): Promise<void> {
  for (
    let current = dir;
    current.startsWith(`${root}${path.sep}`);
    current = path.dirname(current)
  ) {
    if (!fs.existsSync(current)) continue;
    if ((await fsp.readdir(current)).length > 0) return;
    await fsp.rmdir(current);
  }
}

/**
 * Move a staged bundle into the install: the previous release's files that
 * the new one no longer has are removed, its files replace theirs, and
 * everything else (settings, backups) stays as it was.
 */
export async function placeBundle(
  manifest: BundleManifest,
  stagingDir: string,
  installDir: string,
  previouslyOwned: readonly string[],
): Promise<void> {
  await fsp.mkdir(installDir, { recursive: true });
  const next = new Set(manifest.files);
  for (const entry of previouslyOwned.filter((file) => !next.has(file))) {
    const target = path.join(installDir, entry);
    await fsp.rm(target, { recursive: true, force: true });
    await pruneEmptyParents(installDir, path.dirname(target));
  }
  for (const file of manifest.files) {
    const target = path.join(installDir, file);
    await fsp.mkdir(path.dirname(target), { recursive: true });
    await fsp.rename(path.join(stagingDir, file), target);
  }
  await fsp.rm(stagingDir, { recursive: true, force: true });
}

/** The settings an install kept beside its compose files, which no bundle owns. */
const SELFHOST_SETTINGS_FILES = [".env", ".env.bak"];

/**
 * Carry an install's compose settings from the pre-move folder into the current
 * one once its compose files are there; a file already in the current folder
 * wins, and a pre-move folder left empty is removed.
 */
export async function moveLegacySelfhostSettings(
  installDir: string,
): Promise<void> {
  const current = currentSelfhostDir(installDir);
  if (!fs.existsSync(path.join(current, SELFHOST_COMPOSE_FILE))) return;
  const legacy = path.join(installDir, LEGACY_SELFHOST_DIR);
  for (const name of SELFHOST_SETTINGS_FILES) {
    const from = path.join(legacy, name);
    const to = path.join(current, name);
    if (fs.existsSync(from) && !fs.existsSync(to)) await fsp.rename(from, to);
  }
  await pruneEmptyParents(installDir, legacy);
}

/** A release's bundle, downloaded, verified and unpacked beside the install, ready to place. */
export interface StagedBundle {
  manifest: BundleManifest;
  stagingDir: string;
}

/**
 * Download, verify and unpack a release's bundle into a staging directory
 * inside the install (one filesystem, so placing it is a rename per file).
 */
export async function stageBundle(
  installDir: string,
  imageTag: string,
  onProgress: (progress: DownloadProgress) => void,
): Promise<StagedBundle> {
  const archive = await fetchBundle(imageTag, onProgress);
  const stagingDir = path.join(installDir, ".gaia-selfhost-staging");
  const manifest = await unpackBundle(archive, stagingDir, imageTag);
  return { manifest, stagingDir };
}

/**
 * What a git-checkout install owns, for its move to release files: every
 * tracked file and the git directory. Only a clone `gaia up` made qualifies:
 * a release tag checked out detached, with no local changes.
 * @throws Error when the checkout is on a branch, has local changes, or git is missing.
 */
export async function checkoutOwnedFiles(dir: string): Promise<string[]> {
  if (!fs.existsSync(path.join(dir, ".git"))) {
    throw new Error(
      `${dir} holds GAIA's source without its git history, so 'gaia update' can't tell its files from yours.\n` +
        "Install the release with 'gaia up' in a new directory and copy apps/api/.env into it, or update this one from source.",
    );
  }
  const git = (args: string[]) =>
    execa("git", args, { cwd: dir, reject: false });
  const branch = await git(["symbolic-ref", "-q", "--short", "HEAD"]);
  if (branch.exitCode === undefined) {
    throw new Error(
      `${dir} is a git checkout, and moving it to release files needs git to tell its files from yours. Install git and run 'gaia update' again.`,
    );
  }
  if (branch.exitCode === 0) {
    throw new Error(
      `${dir} is a source checkout on the branch ${branch.stdout.trim()}, and 'gaia update' would replace it with release files.\n` +
        "Update it from source with 'gaia update --git'.",
    );
  }
  const status = await git(["status", "--porcelain", "--untracked-files=no"]);
  const changed = status.stdout.split("\n").filter((line) => line.trim());
  if (changed.length > 0) {
    throw new Error(
      `Local changes to these files would be lost when ${dir} moves to release files:\n  ${changed.join("\n  ")}\n` +
        "Commit or discard them, or keep updating from source with 'gaia update --git'.",
    );
  }
  const tracked = await git(["ls-files", "-z"]);
  if (tracked.exitCode !== 0) {
    throw new Error(
      `Could not list the files of ${dir}: ${tracked.stderr.trim()}`,
    );
  }
  return [...tracked.stdout.split("\0").filter(Boolean), ".git"];
}

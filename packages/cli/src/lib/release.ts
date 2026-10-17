/**
 * The GAIA release a CLI version installs: the git tag its infra/docker comes
 * from and the image tag compose pins. `gaia up` and `gaia update` both go
 * through here, so a fresh install and an update land on the same release.
 * @module lib/release
 */

import { execa } from "execa";
import {
  GAIA_VERSION_ENV_KEY,
  setDockerComposeEnvValue,
} from "./env-writer.js";
import { setupRepo } from "./git.js";
import { GAIA_RELEASE_IMAGE_TAG } from "./version.js";

export const GAIA_REPO_URL = "https://github.com/theexperiencecompany/gaia.git";

const INSTALL_SCRIPT_URL = "https://heygaia.io/install.sh";

/** The npm dist-tag a CLI version is published to; install.sh takes it as GAIA_CHANNEL. */
export type CliChannel = "latest" | "beta";

/** A beta CLI version, X.Y.Z-beta.N; publish-cli.yml sends every other release to latest. */
const BETA_VERSION_RE = /^\d+\.\d+\.\d+-beta\.\d+$/;

export function cliChannel(version: string): CliChannel {
  return BETA_VERSION_RE.test(version) ? "beta" : "latest";
}

export function cliInstallCommand(channel: CliChannel): string {
  return channel === "beta"
    ? `curl -fsSL ${INSTALL_SCRIPT_URL} | GAIA_CHANNEL=beta sh`
    : `curl -fsSL ${INSTALL_SCRIPT_URL} | sh`;
}

/**
 * How to get past the release a CLI version installs: a newer CLI on its own
 * channel, and for a beta also the way back to stable.
 */
export function newerReleaseHint(version: string): string[] {
  const channel = cliChannel(version);
  const hint = [
    `For a newer release, update the CLI first (${cliInstallCommand(channel)}), then rerun 'gaia update'.`,
  ];
  if (channel === "beta") {
    hint.push(
      `This is a beta CLI. To move to the stable channel once a stable release newer than ${version} is out, install it with ${cliInstallCommand("latest")} and rerun 'gaia update'.`,
    );
  }
  return hint;
}

/** `git ls-remote --exit-code` status when no ref matched. */
const LS_REMOTE_NO_MATCH = 2;

/** A release image tag, `v<semver>`; publish-cli.yml cuts each from the git tag `cli-v<semver>`. */
const RELEASE_IMAGE_TAG_RE = /^v\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$/;

/**
 * The git tag whose infra/docker matches a release's images.
 * @throws Error when the image tag is not a release (`latest`, a commit sha).
 */
export function releaseGitTag(imageTag: string): string {
  if (!RELEASE_IMAGE_TAG_RE.test(imageTag)) {
    throw new Error(
      `${imageTag} is not a GAIA release tag (v<major>.<minor>.<patch>, e.g. v0.7.0): only a release has compose files that match its images.`,
    );
  }
  return `cli-${imageTag}`;
}

/**
 * Throw unless `remote` publishes the git tag of the release `imageTag`.
 * @throws Error naming the tag when it is missing or the remote is unreachable.
 */
export async function assertReleaseTagPublished(
  remote: string,
  imageTag: string,
  cwd?: string,
): Promise<void> {
  const gitTag = releaseGitTag(imageTag);
  const result = await execa(
    "git",
    ["ls-remote", "--exit-code", "--tags", remote, `refs/tags/${gitTag}`],
    { cwd, reject: false },
  );
  if (result.exitCode === 0) return;
  if (result.exitCode === LS_REMOTE_NO_MATCH) {
    throw new Error(
      `GAIA ${imageTag} has no published release: ${remote} has no tag ${gitTag}.\n` +
        `Install a released CLI (${cliInstallCommand("latest")}) and rerun.`,
    );
  }
  throw new Error(
    `Could not read ${gitTag} from ${remote}: ${result.stderr.trim()}`,
  );
}

/** Pin every GAIA app image in infra/docker/.env to one tag. */
export function pinReleaseImages(repoPath: string, imageTag: string): void {
  setDockerComposeEnvValue(repoPath, GAIA_VERSION_ENV_KEY, imageTag);
}

/**
 * Clone this CLI's release into targetDir and pin its images.
 * @throws Error naming the tag when this CLI version was never released.
 */
export async function cloneRelease(
  targetDir: string,
  repoUrl: string,
  onProgress: (progress: number, phase?: string) => void,
): Promise<void> {
  await assertReleaseTagPublished(repoUrl, GAIA_RELEASE_IMAGE_TAG);
  await setupRepo(
    targetDir,
    repoUrl,
    onProgress,
    releaseGitTag(GAIA_RELEASE_IMAGE_TAG),
  );
  pinReleaseImages(targetDir, GAIA_RELEASE_IMAGE_TAG);
}

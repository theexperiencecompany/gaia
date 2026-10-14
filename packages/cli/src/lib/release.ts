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

export const CLI_INSTALL_COMMAND =
  "curl -fsSL https://heygaia.io/install.sh | sh";

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
        `Install a released CLI (${CLI_INSTALL_COMMAND}) and rerun.`,
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

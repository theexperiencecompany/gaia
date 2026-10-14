import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { execa } from "execa";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const release = vi.hoisted(() => ({ version: "1.2.3" }));
vi.mock("../../src/lib/version.js", () => ({
  get CLI_VERSION() {
    return release.version;
  },
  get GAIA_RELEASE_IMAGE_TAG() {
    return `v${release.version}`;
  },
}));

import { readPinnedGaiaVersion } from "../../src/lib/env-writer.js";
import { cloneRelease } from "../../src/lib/release.js";

const GIT_IDENTITY = ["-c", "user.name=t", "-c", "user.email=t@example.com"];

let root: string;
let origin: string;
let target: string;

async function git(cwd: string, ...args: string[]): Promise<string> {
  const { stdout } = await execa("git", [...GIT_IDENTITY, ...args], { cwd });
  return stdout.trim();
}

async function commit(message: string): Promise<void> {
  fs.mkdirSync(path.join(origin, "infra/docker"), { recursive: true });
  fs.writeFileSync(path.join(origin, "infra/docker/compose.yml"), message);
  await git(origin, "add", ".");
  await git(origin, "commit", "-q", "-m", message);
}

/** An origin whose master is one commit past the CLI's release tag. */
beforeEach(async () => {
  release.version = "1.2.3";
  root = fs.mkdtempSync(path.join(os.tmpdir(), "gaia-release-"));
  origin = path.join(root, "origin");
  fs.mkdirSync(origin);
  await git(origin, "init", "-q", "-b", "master");
  await commit("release");
  await git(origin, "tag", "cli-v1.2.3");
  await commit("unreleased master");
  target = path.join(root, "gaia");
});

afterEach(() => {
  fs.rmSync(root, { recursive: true, force: true });
});

describe("cloneRelease (gaia up's fresh install)", () => {
  it("checks out this CLI's release tag and pins its images, not master", async () => {
    await cloneRelease(target, origin, () => undefined);

    expect(await git(target, "rev-parse", "HEAD")).toBe(
      await git(origin, "rev-parse", "cli-v1.2.3^{commit}"),
    );
    expect(readPinnedGaiaVersion(target)).toBe("v1.2.3");
  });

  it("fails naming the tag when this CLI version was never released", async () => {
    release.version = "9.9.9";

    await expect(cloneRelease(target, origin, () => undefined)).rejects.toThrow(
      /cli-v9\.9\.9/,
    );
    expect(fs.existsSync(target)).toBe(false);
  });
});

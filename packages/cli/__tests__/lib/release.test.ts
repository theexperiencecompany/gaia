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
import {
  cliChannel,
  cloneRelease,
  newerReleaseEnding,
} from "../../src/lib/release.js";

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

describe("a beta CLI release", () => {
  it("clones its own beta tag and pins its beta images", async () => {
    release.version = "1.3.0-beta.1";
    await git(origin, "tag", "cli-v1.3.0-beta.1");
    await commit("after the beta");

    await cloneRelease(target, origin, () => undefined);

    expect(await git(target, "rev-parse", "HEAD")).toBe(
      await git(origin, "rev-parse", "cli-v1.3.0-beta.1^{commit}"),
    );
    expect(readPinnedGaiaVersion(target)).toBe("v1.3.0-beta.1");
  });

  it("is on the beta channel; every other version is on latest", () => {
    expect(cliChannel("1.3.0-beta.1")).toBe("beta");
    expect(cliChannel("1.3.0")).toBe("latest");
    expect(cliChannel("1.3.0-rc.1")).toBe("latest");
  });

  it("tells a beta install to update on beta and how to move to stable", () => {
    const ending = newerReleaseEnding("1.3.0-beta.1");

    expect(ending.target).toBe(
      "curl -fsSL https://heygaia.io/install.sh | GAIA_CHANNEL=beta sh",
    );
    expect(ending.also?.at(-1)).toBe(
      "This is a beta CLI; the stable channel installs with curl -fsSL https://heygaia.io/install.sh | sh",
    );
  });

  it("gives a stable install only the stable install command", () => {
    expect(newerReleaseEnding("1.2.3")).toEqual({
      lead: "For a newer release, update the CLI:",
      target: "curl -fsSL https://heygaia.io/install.sh | sh",
      also: ["Then run 'gaia update' again."],
    });
  });
});

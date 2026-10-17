import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { execa } from "execa";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { pullSelfhostImages, startServices } = vi.hoisted(() => ({
  pullSelfhostImages: vi.fn(),
  startServices: vi.fn(),
}));
vi.mock("../../src/lib/service-starter.js", () => ({
  pullSelfhostImages,
  startServices,
}));
vi.mock("../../src/lib/version.js", () => ({
  CLI_VERSION: "1.2.3",
  GAIA_RELEASE_IMAGE_TAG: "v1.2.3",
}));

import {
  applyReleaseUpdate,
  decideReleaseUpdate,
  isReleaseCurrent,
  planReleaseUpdate,
} from "../../src/commands/update/flow.js";

const COMPOSE = "infra/docker/docker-compose.selfhost.yml";
const GIT_IDENTITY = [
  "-c",
  "user.name=test",
  "-c",
  "user.email=test@example.com",
];

/** Progress lines are UI; these tests assert on the install itself. */
const ignoreStatus = vi.fn();

let root: string;
let origin: string;
let install: string;

async function git(cwd: string, ...args: string[]): Promise<string> {
  const { stdout } = await execa("git", [...GIT_IDENTITY, ...args], { cwd });
  return stdout.trim();
}

async function commitCompose(repo: string, body: string): Promise<void> {
  fs.mkdirSync(path.join(repo, "infra/docker"), { recursive: true });
  fs.writeFileSync(path.join(repo, COMPOSE), body);
  await git(repo, "add", ".");
  await git(repo, "commit", "-q", "-m", body);
}

function composeEnv(): string {
  const envPath = path.join(install, "infra/docker/.env");
  return fs.existsSync(envPath) ? fs.readFileSync(envPath, "utf-8") : "";
}

/** An origin with the CLI's release tag one commit behind master, and a master clone of it. */
beforeEach(async () => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), "gaia-update-"));
  origin = path.join(root, "origin");
  fs.mkdirSync(origin);
  await git(origin, "init", "-q", "-b", "master");
  await commitCompose(origin, "release compose");
  await git(origin, "tag", "cli-v1.2.3");
  await commitCompose(origin, "master compose");
  install = path.join(root, "install");
  await git(root, "clone", "-q", "--no-tags", origin, install);
  pullSelfhostImages.mockReset();
  startServices.mockReset();
});

afterEach(() => {
  fs.rmSync(root, { recursive: true, force: true });
});

describe("gaia update (release mode)", () => {
  it("plans a move from unpinned images and master files to the CLI's release", async () => {
    const plan = await planReleaseUpdate(install, "v1.2.3");

    expect(plan.fromVersion).toBe("latest");
    expect(plan.toVersion).toBe("v1.2.3");
    expect(plan.checkout?.toTag).toBe("cli-v1.2.3");
    expect(plan.checkout?.atTag).toBe(false);
    expect(isReleaseCurrent(plan)).toBe(false);
  });

  it("changes nothing when the release images cannot be pulled", async () => {
    pullSelfhostImages.mockRejectedValue(new Error("manifest unknown"));
    const before = await git(install, "rev-parse", "HEAD");
    const plan = await planReleaseUpdate(install, "v1.2.3");

    await expect(applyReleaseUpdate(plan, ignoreStatus)).rejects.toThrow(
      "manifest unknown",
    );

    expect(await git(install, "rev-parse", "HEAD")).toBe(before);
    expect(composeEnv()).not.toContain("GAIA_VERSION");
    expect(startServices).not.toHaveBeenCalled();
  });

  it("checks out the release files, pins the tag and is then current", async () => {
    pullSelfhostImages.mockResolvedValue(undefined);
    startServices.mockResolvedValue(undefined);
    const plan = await planReleaseUpdate(install, "v1.2.3");

    await applyReleaseUpdate(plan, ignoreStatus);

    expect(pullSelfhostImages).toHaveBeenCalledWith(install, "v1.2.3");
    expect(fs.readFileSync(path.join(install, COMPOSE), "utf-8")).toBe(
      "release compose",
    );
    expect(composeEnv()).toMatch(/^GAIA_VERSION=v1\.2\.3$/m);
    expect(isReleaseCurrent(await planReleaseUpdate(install, "v1.2.3"))).toBe(
      true,
    );
  });

  it("--version moves the compose files to that release too, not only the images", async () => {
    pullSelfhostImages.mockResolvedValue(undefined);
    startServices.mockResolvedValue(undefined);
    await commitCompose(origin, "1.2.2 compose");
    await git(origin, "tag", "cli-v1.2.2");
    const plan = await planReleaseUpdate(install, "v1.2.2");

    await applyReleaseUpdate(plan, ignoreStatus);

    expect(plan.checkout?.toTag).toBe("cli-v1.2.2");
    expect(fs.readFileSync(path.join(install, COMPOSE), "utf-8")).toBe(
      "1.2.2 compose",
    );
    expect(composeEnv()).toMatch(/^GAIA_VERSION=v1\.2\.2$/m);
  });

  it("--version refuses an image tag that names no release", async () => {
    await expect(planReleaseUpdate(install, "latest")).rejects.toThrow(
      /latest is not a GAIA release/,
    );
  });

  it("--version fails naming the git tag of a release origin never published", async () => {
    await expect(planReleaseUpdate(install, "v9.9.9")).rejects.toThrow(
      /cli-v9\.9\.9/,
    );
  });

  it("refuses to overwrite local edits to tracked files", async () => {
    pullSelfhostImages.mockResolvedValue(undefined);
    fs.writeFileSync(path.join(install, COMPOSE), "hand edited");
    const plan = await planReleaseUpdate(install, "v1.2.3");

    await expect(applyReleaseUpdate(plan, ignoreStatus)).rejects.toThrow(
      /Local changes to tracked files[\s\S]*docker-compose\.selfhost\.yml/,
    );
    expect(pullSelfhostImages).not.toHaveBeenCalled();
    expect(fs.readFileSync(path.join(install, COMPOSE), "utf-8")).toBe(
      "hand edited",
    );
  });
});
describe("decideReleaseUpdate", () => {
  const missing = { kind: "not-published", image: "gaia-web:v0.6.0" } as const;

  // cli-audit 25: an install on `latest` was offered "latest -> v0.6.0", a downgrade to unpublished images.
  it("offers nothing to a development build", () => {
    expect(
      decideReleaseUpdate({
        current: "latest",
        target: "v0.6.0",
        explicit: false,
        gap: missing,
      }),
    ).toEqual({ kind: "development-build" });
  });

  it("offers nothing when the target is not newer", () => {
    expect(
      decideReleaseUpdate({
        current: "v0.6.0",
        target: "v0.6.0",
        explicit: false,
        gap: null,
      }),
    ).toEqual({ kind: "up-to-date" });
    expect(
      decideReleaseUpdate({
        current: "v0.7.0",
        target: "v0.6.0",
        explicit: false,
        gap: null,
      }),
    ).toEqual({ kind: "up-to-date" });
  });

  it("offers nothing when the newer release's images are missing here", () => {
    expect(
      decideReleaseUpdate({
        current: "v0.5.0",
        target: "v0.6.0",
        explicit: false,
        gap: missing,
      }),
    ).toEqual({ kind: "unavailable", gap: missing });
  });

  it("offers a newer release whose images exist", () => {
    expect(
      decideReleaseUpdate({
        current: "v0.5.0",
        target: "v0.6.0",
        explicit: false,
        gap: null,
      }),
    ).toEqual({ kind: "offer", downgrade: false });
  });

  it("lets an explicit --version move back, and says it is a downgrade", () => {
    expect(
      decideReleaseUpdate({
        current: "v0.7.0",
        target: "v0.6.0",
        explicit: true,
        gap: null,
      }),
    ).toEqual({ kind: "offer", downgrade: true });
  });
});

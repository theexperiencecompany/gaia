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
import type { UpdateReporter } from "../../src/commands/update/flow.types.js";
import { readBundleManifest } from "../../src/lib/selfhost-bundle.js";
import { buildBundle, serveBundles, writeFile } from "../lib/bundle-fixture.js";

const COMPOSE = "packages/cli/selfhost/docker-compose.selfhost.yml";
const CADDYFILE = "packages/cli/selfhost/Caddyfile";
/** Where releases before the move to packages/cli kept the compose files and their .env. */
const OLD_COMPOSE = "infra/docker/docker-compose.selfhost.yml";
const OLD_COMPOSE_ENV = "infra/docker/.env";
const COMPOSE_ENV = "packages/cli/selfhost/.env";
const GIT_IDENTITY = [
  "-c",
  "user.name=test",
  "-c",
  "user.email=test@example.com",
];

/** Progress lines are UI; these tests assert on the install itself. */
const quiet: UpdateReporter = {
  onStage: () => undefined,
  onBundleDownload: () => undefined,
  onCompose: () => undefined,
};

let root: string;
let install: string;

async function git(cwd: string, ...args: string[]): Promise<string> {
  const { stdout } = await execa("git", [...GIT_IDENTITY, ...args], { cwd });
  return stdout.trim();
}

const read = (file: string) =>
  fs.readFileSync(path.join(install, file), "utf-8");
const exists = (file: string) => fs.existsSync(path.join(install, file));

/** The compose env file the install runs with: the current layout's, else the pre-move one. */
function composeEnv(): string {
  if (exists(COMPOSE)) return exists(COMPOSE_ENV) ? read(COMPOSE_ENV) : "";
  return exists(OLD_COMPOSE_ENV) ? read(OLD_COMPOSE_ENV) : "";
}

/**
 * The install `gaia up` used to make: a clone of the repo at the release tag,
 * detached, with the user's settings and a backup beside the tracked files.
 */
async function gitCheckoutInstall(): Promise<void> {
  fs.mkdirSync(install);
  await git(install, "init", "-q", "-b", "master");
  writeFile(install, OLD_COMPOSE, "checkout compose");
  writeFile(install, "apps/api/app/main.py", "source");
  writeFile(install, ".gitignore", ".env\nbackups/\n");
  await git(install, "add", ".");
  await git(install, "commit", "-q", "-m", "release");
  await git(install, "tag", "cli-v1.2.2");
  await git(install, "checkout", "-q", "--detach", "cli-v1.2.2");
  writeFile(install, "apps/api/.env", "INSTANCE_SECRET=keep");
  writeFile(
    install,
    OLD_COMPOSE_ENV,
    "GAIA_VERSION=v1.2.2\nWEB_HOST_PORT=3100\n",
  );
  writeFile(install, "backups/2026-10-01/mongo.archive", "data");
}

function releases(): Record<string, Buffer> {
  return {
    "v1.2.3": buildBundle(root, "v1.2.3", {
      [COMPOSE]: "1.2.3 compose",
      [CADDYFILE]: "1.2.3 caddy",
    }),
    "v1.2.4": buildBundle(root, "v1.2.4", { [COMPOSE]: "1.2.4 compose" }),
  };
}

beforeEach(() => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), "gaia-update-"));
  install = path.join(root, "install");
  pullSelfhostImages.mockReset();
  startServices.mockReset();
  pullSelfhostImages.mockResolvedValue(undefined);
  startServices.mockResolvedValue({ startedServices: 0 });
});

afterEach(() => {
  vi.unstubAllGlobals();
  fs.rmSync(root, { recursive: true, force: true });
});

describe("gaia update (release mode)", () => {
  it("moves a git-checkout install to the release's setup files, keeping settings and data", async () => {
    await gitCheckoutInstall();
    serveBundles(releases());
    const plan = await planReleaseUpdate(install, "v1.2.3");
    expect(plan.layout.kind).toBe("checkout");

    await applyReleaseUpdate(plan, quiet);

    expect(read(COMPOSE)).toBe("1.2.3 compose");
    expect(read(CADDYFILE)).toBe("1.2.3 caddy");
    // The compose settings moved with the files; nothing is left where they were.
    expect(composeEnv()).toMatch(/^WEB_HOST_PORT=3100$/m);
    expect(exists(OLD_COMPOSE)).toBe(false);
    expect(exists("infra")).toBe(false);
    expect(exists(".git")).toBe(false);
    expect(exists("apps/api/app/main.py")).toBe(false);
    expect(read("apps/api/.env")).toBe("INSTANCE_SECRET=keep");
    expect(read("backups/2026-10-01/mongo.archive")).toBe("data");
    expect(composeEnv()).toMatch(/^GAIA_VERSION=v1\.2\.3$/m);
    expect(pullSelfhostImages).toHaveBeenCalledWith(
      install,
      "v1.2.3",
      quiet.onCompose,
    );
    expect(readBundleManifest(install)?.version).toBe("v1.2.3");
    expect(isReleaseCurrent(await planReleaseUpdate(install, "v1.2.3"))).toBe(
      true,
    );
  });

  it("swaps one release's setup files for the next and drops the ones it no longer has", async () => {
    await gitCheckoutInstall();
    serveBundles(releases());
    await applyReleaseUpdate(await planReleaseUpdate(install, "v1.2.3"), quiet);

    const plan = await planReleaseUpdate(install, "v1.2.4");
    expect(plan.layout.kind).toBe("bundle");
    expect(isReleaseCurrent(plan)).toBe(false);
    await applyReleaseUpdate(plan, quiet);

    expect(read(COMPOSE)).toBe("1.2.4 compose");
    expect(exists(CADDYFILE)).toBe(false);
    expect(read("apps/api/.env")).toBe("INSTANCE_SECRET=keep");
    expect(composeEnv()).toMatch(/^GAIA_VERSION=v1\.2\.4$/m);
  });

  it("changes nothing when the release images cannot be pulled", async () => {
    await gitCheckoutInstall();
    serveBundles(releases());
    pullSelfhostImages.mockRejectedValue(new Error("manifest unknown"));
    const plan = await planReleaseUpdate(install, "v1.2.3");

    await expect(applyReleaseUpdate(plan, quiet)).rejects.toThrow(
      "manifest unknown",
    );

    expect(read(OLD_COMPOSE)).toBe("checkout compose");
    expect(exists(".git")).toBe(true);
    expect(composeEnv()).toMatch(/^GAIA_VERSION=v1\.2\.2$/m);
    expect(exists(".gaia-selfhost-staging")).toBe(false);
    expect(startServices).not.toHaveBeenCalled();
  });

  it("fails before pulling anything when the release has no setup files", async () => {
    await gitCheckoutInstall();
    serveBundles(releases());
    const plan = await planReleaseUpdate(install, "v9.9.9");

    await expect(applyReleaseUpdate(plan, quiet)).rejects.toThrow(
      /GAIA v9\.9\.9 has no published setup files/,
    );
    expect(pullSelfhostImages).not.toHaveBeenCalled();
    expect(read(OLD_COMPOSE)).toBe("checkout compose");
  });

  it("--version refuses an image tag that names no release", async () => {
    await gitCheckoutInstall();
    await expect(planReleaseUpdate(install, "latest")).rejects.toThrow(
      /latest is not a GAIA release/,
    );
  });

  it("refuses to replace a checkout with local edits to its files", async () => {
    await gitCheckoutInstall();
    fs.writeFileSync(path.join(install, OLD_COMPOSE), "hand edited");

    await expect(planReleaseUpdate(install, "v1.2.3")).rejects.toThrow(
      /Local changes[\s\S]*docker-compose\.selfhost\.yml/,
    );
    expect(read(OLD_COMPOSE)).toBe("hand edited");
  });

  it("leaves a developer's checkout on a branch to --git", async () => {
    await gitCheckoutInstall();
    await git(install, "checkout", "-q", "master");

    await expect(planReleaseUpdate(install, "v1.2.3")).rejects.toThrow(
      /gaia update --git/,
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

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { readConfig } = vi.hoisted(() => ({ readConfig: vi.fn() }));
vi.mock("../../src/lib/config.js", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  readConfig,
  updateConfig: vi.fn(),
}));

import {
  describeInstall,
  detectSetupMode,
  findInstallRoot,
  findRepoRoot,
  isSelfhostOrUnconfigured,
} from "../../src/lib/install-root.js";

let root: string;

/** A GAIA checkout under the temp root; configured ones carry apps/api/.env. */
function checkout(name: string, apiEnv?: string): string {
  const dir = path.join(root, name);
  fs.mkdirSync(path.join(dir, "apps/api/app/config"), { recursive: true });
  fs.writeFileSync(
    path.join(dir, "apps/api/app/config/settings_validator.py"),
    "",
  );
  if (apiEnv !== undefined) {
    fs.writeFileSync(path.join(dir, "apps/api/.env"), apiEnv);
  }
  return dir;
}

beforeEach(() => {
  root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "gaia-root-")));
  readConfig.mockReset();
});

afterEach(() => {
  fs.rmSync(root, { recursive: true, force: true });
});

describe("findInstallRoot", () => {
  it("inspects the recorded install when cwd is an unconfigured source checkout", () => {
    const install = checkout("gaia", "SETUP_MODE=selfhost\n");
    const source = checkout("gaia-src");
    readConfig.mockReturnValue({ repoPath: install });

    expect(findInstallRoot(path.join(source, "apps"))).toBe(install);
  });

  it("keeps a configured checkout in cwd over the recorded install", () => {
    const install = checkout("gaia", "SETUP_MODE=selfhost\n");
    const dev = checkout("dev", "SETUP_MODE=developer\n");
    readConfig.mockReturnValue({ repoPath: install });

    expect(findInstallRoot(dev)).toBe(dev);
  });

  it("falls back to the unconfigured cwd checkout when nothing is recorded", () => {
    const source = checkout("gaia-src");
    readConfig.mockReturnValue(null);

    expect(findInstallRoot(source)).toBe(source);
  });
});

describe("findRepoRoot", () => {
  it("still targets the cwd checkout that setup is about to configure", () => {
    const install = checkout("gaia", "SETUP_MODE=selfhost\n");
    const source = checkout("gaia-src");
    readConfig.mockReturnValue({ repoPath: install });

    expect(findRepoRoot(source)).toBe(source);
  });
});

describe("describeInstall", () => {
  it("names the path and mode a command inspects", () => {
    expect(describeInstall("/home/me/gaia", "selfhost")).toBe(
      "/home/me/gaia (self-host)",
    );
  });

  it("flags a checkout that was never configured", () => {
    expect(describeInstall("/home/me/gaia-src", null)).toBe(
      "/home/me/gaia-src (not set up yet: no apps/api/.env)",
    );
  });

  it("says when there is nothing to inspect", () => {
    expect(describeInstall(null, null)).toBe("GAIA isn't installed yet");
  });
});

describe("detectSetupMode", () => {
  it("reads a quoted SETUP_MODE", async () => {
    const dir = checkout("quoted", 'SETUP_MODE="selfhost"\n');
    expect(await detectSetupMode(dir)).toBe("selfhost");
  });

  it("falls back to where MONGO_DB points when SETUP_MODE is absent", async () => {
    const selfhost = checkout(
      "old-selfhost",
      "MONGO_DB=mongodb://mongo:27017/gaia\n",
    );
    const dev = checkout(
      "old-dev",
      "MONGO_DB=mongodb://localhost:27017/gaia\n",
    );
    expect(await detectSetupMode(selfhost)).toBe("selfhost");
    expect(await detectSetupMode(dev)).toBe("developer");
  });

  it("ignores a commented-out line", async () => {
    const dir = checkout(
      "commented",
      "# MONGO_DB=mongodb://mongo:27017/gaia\nMONGO_DB=mongodb+srv://cluster.example/gaia\n",
    );
    expect(await detectSetupMode(dir)).toBeNull();
  });

  it("says nothing when the .env names no mode", async () => {
    const dir = checkout("unknown", "OPENAI_API_KEY=sk-test\n");
    expect(await detectSetupMode(dir)).toBeNull();
  });

  it("says nothing for an unconfigured checkout", async () => {
    expect(await detectSetupMode(checkout("bare"))).toBeNull();
  });
});

describe("isSelfhostOrUnconfigured", () => {
  it("lets the CLI write a self-host install or one with no .env yet", async () => {
    expect(
      await isSelfhostOrUnconfigured(checkout("sh", "SETUP_MODE=selfhost\n")),
    ).toBe(true);
    expect(await isSelfhostOrUnconfigured(checkout("fresh"))).toBe(true);
  });

  it("protects a developer .env and one that names no mode", async () => {
    expect(
      await isSelfhostOrUnconfigured(checkout("dev", "SETUP_MODE=developer\n")),
    ).toBe(false);
    expect(
      await isSelfhostOrUnconfigured(checkout("odd", "OPENAI_API_KEY=sk\n")),
    ).toBe(false);
  });
});

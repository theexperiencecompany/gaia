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
  findInstallRoot,
  findRepoRoot,
} from "../../src/lib/service-starter.js";

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

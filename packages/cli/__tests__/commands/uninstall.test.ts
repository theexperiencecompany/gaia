import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  KEPT_SETTINGS_FILES,
  removeInstallFiles,
} from "../../src/commands/uninstall/flow.js";
import { composeDownArgs } from "../../src/lib/service-starter.js";

describe("composeDownArgs", () => {
  it("only stops and removes containers for gaia stop", () => {
    expect(composeDownArgs()).toEqual(["down"]);
  });

  it("also removes the images when uninstalling, but keeps the volumes", () => {
    expect(composeDownArgs({ remove: { volumes: false } })).toEqual([
      "down",
      "--rmi",
      "all",
      "--remove-orphans",
    ]);
  });

  it("removes the volumes only when the data is to go too", () => {
    expect(composeDownArgs({ remove: { volumes: true } })).toEqual([
      "down",
      "--rmi",
      "all",
      "--remove-orphans",
      "--volumes",
    ]);
  });
});

describe("removeInstallFiles", () => {
  const dirs: string[] = [];

  afterEach(() => {
    for (const dir of dirs.splice(0)) {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  function makeInstall(): string {
    const root = mkdtempSync(path.join(tmpdir(), "gaia-uninstall-"));
    dirs.push(root);
    const install = path.join(root, "gaia");
    for (const dir of ["apps/api", "apps/web", "infra/docker/selfhost"]) {
      mkdirSync(path.join(install, dir), { recursive: true });
    }
    for (const file of [
      "apps/api/.env",
      "apps/api/.env.bak",
      "apps/web/.env",
      "infra/docker/.env",
      "infra/docker/docker-compose.selfhost.yml",
      "infra/docker/selfhost/Caddyfile",
      "selfhost-manifest.json",
    ]) {
      writeFileSync(path.join(install, file), "x");
    }
    return install;
  }

  it("deletes the whole install when the data goes too", () => {
    const install = makeInstall();

    removeInstallFiles(install, { keepSettings: false });

    expect(existsSync(install)).toBe(false);
  });

  it("keeps only the settings the kept data needs, so gaia up picks it back up", () => {
    const install = makeInstall();

    removeInstallFiles(install, { keepSettings: true });

    expect(readdirSync(install).sort()).toEqual(["apps", "infra"]);
    expect(readdirSync(path.join(install, "apps"))).toEqual(["api"]);
    expect(readdirSync(path.join(install, "apps", "api"))).toEqual([".env"]);
    expect(readdirSync(path.join(install, "infra", "docker"))).toEqual([
      ".env",
    ]);
    expect(KEPT_SETTINGS_FILES).toEqual(["apps/api/.env", "infra/docker/.env"]);
  });
});

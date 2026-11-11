import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { execa, findInstallRoot, startServices } = vi.hoisted(() => ({
  execa: vi.fn(),
  findInstallRoot: vi.fn(),
  startServices: vi.fn(),
}));
vi.mock("execa", () => ({ execa }));
vi.mock("../../src/lib/docker.js", () => ({
  isDockerRunning: async () => true,
}));
vi.mock("../../src/lib/install-root.js", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/lib/install-root.js")>()),
  findInstallRoot,
}));
vi.mock("../../src/lib/service-starter.js", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("../../src/lib/service-starter.js")
  >()),
  startServices,
}));

import { runRestore } from "../../src/commands/restore/flow.js";
import { backupFileSet } from "../../src/lib/backup-files.js";

const STAMP = "2026-10-14T09-30-05Z";

let install: string;
let backups: string;

beforeEach(() => {
  install = fs.mkdtempSync(path.join(os.tmpdir(), "gaia-install-"));
  fs.mkdirSync(path.join(install, "infra", "docker"), { recursive: true });
  fs.writeFileSync(
    path.join(install, "infra", "docker", "docker-compose.selfhost.yml"),
    "",
  );
  fs.mkdirSync(path.join(install, "apps", "api"), { recursive: true });
  fs.writeFileSync(
    path.join(install, "apps", "api", ".env"),
    "INSTANCE_SECRET=fresh\n",
  );
  backups = fs.mkdtempSync(path.join(os.tmpdir(), "gaia-backups-"));
  findInstallRoot.mockReturnValue(install);
  startServices.mockReset().mockResolvedValue({ startedServices: 9 });
  execa.mockReset().mockResolvedValue({ exitCode: 0 });
});

describe("gaia restore", () => {
  it("restarts the stack the way gaia start does, so the restored settings load", async () => {
    const files = backupFileSet(backups, STAMP);
    fs.writeFileSync(files.apiEnvFile, "INSTANCE_SECRET=original\n");

    await runRestore(
      { fromDir: backups },
      { onPart: vi.fn(), onRestart: vi.fn() },
    );

    expect(startServices).toHaveBeenCalledOnce();
    expect(startServices.mock.calls[0]?.slice(0, 2)).toEqual([
      install,
      "selfhost",
    ]);
  });

  it("a dry run restarts nothing", async () => {
    fs.writeFileSync(backupFileSet(backups, STAMP).apiEnvFile, "x\n");

    await runRestore(
      { fromDir: backups, dryRun: true },
      { onPart: vi.fn(), onRestart: vi.fn() },
    );

    expect(startServices).not.toHaveBeenCalled();
  });
});

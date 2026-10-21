import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { execa, findInstallRoot } = vi.hoisted(() => ({
  execa: vi.fn(),
  findInstallRoot: vi.fn(),
}));
vi.mock("execa", async (importOriginal) => ({
  ...(await importOriginal<typeof import("execa")>()),
  execa,
}));
vi.mock("../../src/lib/docker-access.js", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/lib/docker-access.js")>()),
  getDockerAccess: async () => "ready",
}));
vi.mock("../../src/lib/service-starter.js", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("../../src/lib/service-starter.js")
  >()),
  findInstallRoot,
}));

import { runBackup } from "../../src/commands/backup/flow.js";

let install: string;

beforeEach(() => {
  install = fs.mkdtempSync(path.join(os.tmpdir(), "gaia-install-"));
  fs.mkdirSync(path.join(install, "infra", "docker"), { recursive: true });
  fs.writeFileSync(
    path.join(install, "infra", "docker", "docker-compose.selfhost.yml"),
    "",
  );
  findInstallRoot.mockReturnValue(install);
  execa.mockReset();
});

describe("gaia backup on a stopped GAIA", () => {
  // Real run: an uninstall's backup of a stopped GAIA dumped docker's whole command line and its stderr.
  it("says GAIA isn't running and how to start it, before dumping anything", async () => {
    // `docker ps`: the databases' containers are gone after 'gaia stop'.
    execa.mockResolvedValue({ stdout: "" });

    await expect(
      runBackup({ outputDir: path.join(install, "backups") }),
    ).rejects.toThrow(
      "GAIA isn't running, so its databases can't be backed up.\nStart it with 'gaia start', then try again.",
    );
    expect(fs.existsSync(path.join(install, "backups"))).toBe(false);
  });
});

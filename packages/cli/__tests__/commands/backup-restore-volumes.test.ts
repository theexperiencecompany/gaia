import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import { getBackupCommands } from "../../src/commands/backup/flow.js";
import {
  getRestoreCommands,
  resolveRestoreFiles,
} from "../../src/commands/restore/flow.js";

describe("backup and restore cover the self-host storage volumes", () => {
  it("archives the workspace and uploaded files with the databases", () => {
    const cmds = getBackupCommands("/b", "2026-10-14").join("\n");

    expect(cmds).toContain(
      "-v gaia-selfhost_workspace:/data -v /b:/backups alpine tar czf /backups/workspace-2026-10-14.tar.gz",
    );
    expect(cmds).toContain(
      "-v gaia-selfhost_files:/data -v /b:/backups alpine tar czf /backups/files-2026-10-14.tar.gz",
    );
    expect(cmds).not.toContain("gaia-sandbox-workspace");
  });

  it("restores each archive found in a backup dir into its own volume", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "gaia-restore-"));
    for (const name of [
      "workspace-2026-10-13.tar.gz",
      "workspace-2026-10-14.tar.gz",
      "files-2026-10-14.tar.gz",
      "sandbox-workspace-2026-10-01.tar.gz",
    ]) {
      fs.writeFileSync(path.join(dir, name), "");
    }

    const resolved = resolveRestoreFiles({ fromDir: dir });

    expect(
      resolved.volumeFiles.map((v) => [v.volume, path.basename(v.file)]),
    ).toEqual([
      ["gaia-selfhost_workspace", "workspace-2026-10-14.tar.gz"],
      ["gaia-selfhost_files", "files-2026-10-14.tar.gz"],
    ]);
    const cmds = getRestoreCommands(resolved);
    expect(cmds).toHaveLength(2);
    expect(cmds[0]).toContain("-v gaia-selfhost_workspace:/data");
    expect(cmds[0]).toContain("tar xzf /backups/workspace-2026-10-14.tar.gz");
  });
});

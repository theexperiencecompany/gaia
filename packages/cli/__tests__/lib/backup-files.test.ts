import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import { getBackupCommands } from "../../src/commands/backup/flow.js";
import { resolveRestoreFiles } from "../../src/commands/restore/flow.js";
import {
  backupFileSet,
  backupStamp,
  partialPath,
} from "../../src/lib/backup-files.js";

function dirWith(names: string[]): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "gaia-backups-"));
  for (const name of names) fs.writeFileSync(path.join(dir, name), "");
  return dir;
}

describe("backup files are named per run and restored as one set", () => {
  it("names a run by its UTC second, without characters filesystems reject", () => {
    expect(backupStamp(new Date("2026-10-14T09:30:05.123Z"))).toBe(
      "2026-10-14T09-30-05Z",
    );
  });

  it("two runs on one day write different files", () => {
    const morning = backupFileSet("/b", "2026-10-14T09-30-05Z");
    const evening = backupFileSet("/b", "2026-10-14T21-00-00Z");

    expect(morning.mongoFile).not.toBe(evening.mongoFile);
    expect(getBackupCommands("/b", "2026-10-14T09-30-05Z")).toContain(
      "install -m 600 ../../apps/api/.env /b/api-env-2026-10-14T09-30-05Z.env",
    );
  });

  it("restores every file of the newest run, never mixing in an older one", () => {
    const dir = dirWith([
      "mongo-2026-10-14.gz",
      "postgres-2026-10-14.sql",
      "api-env-2026-10-14.env",
      "workspace-2026-10-14.tar.gz",
      "mongo-2026-10-14T09-30-05Z.gz",
      "postgres-2026-10-14T09-30-05Z.sql",
      "api-env-2026-10-14T09-30-05Z.env",
    ]);

    const resolved = resolveRestoreFiles({ fromDir: dir });

    expect(path.basename(resolved.mongoFile ?? "")).toBe(
      "mongo-2026-10-14T09-30-05Z.gz",
    );
    expect(path.basename(resolved.postgresFile ?? "")).toBe(
      "postgres-2026-10-14T09-30-05Z.sql",
    );
    expect(path.basename(resolved.apiEnvFile ?? "")).toBe(
      "api-env-2026-10-14T09-30-05Z.env",
    );
    expect(resolved.volumeFiles).toEqual([]);
  });

  it("an unfinished run's partial files are never restored", () => {
    const done = backupFileSet("/x", "2026-10-14T09-30-05Z");
    const failed = backupFileSet("/x", "2026-10-14T21-00-00Z");
    const dir = dirWith([
      path.basename(done.mongoFile),
      path.basename(done.postgresFile),
      path.basename(partialPath(failed.mongoFile)),
    ]);

    const resolved = resolveRestoreFiles({ fromDir: dir });

    expect(path.basename(resolved.mongoFile ?? "")).toBe(
      path.basename(done.mongoFile),
    );
  });
});

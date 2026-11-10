import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import {
  backupApiEnv,
  getBackupCommands,
} from "../../src/commands/backup/flow.js";
import {
  getRestoreCommands,
  resolveRestoreFiles,
  restoreApiEnv,
  restoreWarnings,
} from "../../src/commands/restore/flow.js";

const ORIGINAL_SECRET =
  "INSTANCE_SECRET=original-key-the-dump-was-encrypted-under";

function installWithEnv(contents: string): string {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "gaia-install-"));
  fs.mkdirSync(path.join(root, "apps", "api"), { recursive: true });
  fs.writeFileSync(path.join(root, "apps", "api", ".env"), contents);
  return root;
}

describe("backup and restore carry the key the stored credentials need", () => {
  it("a clean install gets the backed-up INSTANCE_SECRET back", () => {
    const original = installWithEnv(`ENV=selfhost\n${ORIGINAL_SECRET}\n`);
    const backups = fs.mkdtempSync(path.join(os.tmpdir(), "gaia-backups-"));
    backupApiEnv(original, path.join(backups, "api-env-2026-10-14.env"));

    // `gaia up` on a fresh machine generates a new, different secret.
    const fresh = installWithEnv("ENV=selfhost\nINSTANCE_SECRET=fresh\n");
    const resolved = resolveRestoreFiles({ fromDir: backups });
    expect(resolved.apiEnvFile).toBeDefined();
    restoreApiEnv(resolved.apiEnvFile as string, fresh);

    const restored = path.join(fresh, "apps", "api", ".env");
    expect(fs.readFileSync(restored, "utf-8")).toContain(ORIGINAL_SECRET);
    expect(fs.statSync(restored).mode & 0o777).toBe(0o600);
    expect(fs.readFileSync(`${restored}.bak`, "utf-8")).toContain(
      "INSTANCE_SECRET=fresh",
    );
  });

  it("the backup copy of apps/api/.env is owner-only", () => {
    const install = installWithEnv(`${ORIGINAL_SECRET}\n`);
    const target = path.join(
      fs.mkdtempSync(path.join(os.tmpdir(), "gaia-backups-")),
      "api-env-2026-10-14.env",
    );

    backupApiEnv(install, target);

    expect(fs.statSync(target).mode & 0o777).toBe(0o600);
  });

  it("a backup of an install with no apps/api/.env fails instead of shipping undecryptable credentials", () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "gaia-install-"));

    expect(() =>
      backupApiEnv(root, path.join(root, "api-env-2026-10-14.env")),
    ).toThrow(/INSTANCE_SECRET/);
  });

  it("a second same-day backup's .bak is never picked as the env to restore", () => {
    const backups = fs.mkdtempSync(path.join(os.tmpdir(), "gaia-backups-"));
    fs.writeFileSync(path.join(backups, "api-env-2026-10-14.env"), "new");
    fs.writeFileSync(path.join(backups, "api-env-2026-10-14.env.bak"), "old");

    const resolved = resolveRestoreFiles({ fromDir: backups });

    expect(resolved.apiEnvFile).toBe(
      path.join(backups, "api-env-2026-10-14.env"),
    );
  });

  it("the manual commands back up and restore apps/api/.env", () => {
    expect(getBackupCommands("/b", "2026-10-14")).toContain(
      "install -m 600 ../../apps/api/.env /b/api-env-2026-10-14.env",
    );
    expect(
      getRestoreCommands({
        apiEnvFile: "/b/api-env-2026-10-14.env",
        volumeFiles: [],
      })[0],
    ).toBe("install -m 600 /b/api-env-2026-10-14.env ../../apps/api/.env");
  });

  it("explicit dump files restore the backed-up apps/api/.env given with --env", () => {
    const resolved = resolveRestoreFiles({
      mongoFile: "/b/mongo.gz",
      apiEnvFile: "/b/api-env.env",
    });

    expect(resolved.apiEnvFile).toBe("/b/api-env.env");
    expect(getRestoreCommands(resolved)[0]).toBe(
      "install -m 600 /b/api-env.env ../../apps/api/.env",
    );
    expect(restoreWarnings(resolved)).toEqual([]);
  });

  it("a Mongo restore without the backup's apps/api/.env warns that credentials may not decrypt", () => {
    const resolved = resolveRestoreFiles({ mongoFile: "/b/mongo.gz" });

    expect(restoreWarnings(resolved).join("\n")).toMatch(
      /INSTANCE_SECRET[\s\S]*--env/,
    );
  });
});

/**
 * The files one `gaia backup` run writes, named by the run's stamp, shared so
 * `gaia restore` always reloads a single run's files together.
 *
 * @module lib/backup-files
 */

import * as fs from "node:fs";
import * as path from "node:path";
import {
  VOLUME_BACKUPS,
  type VolumeBackup,
  type VolumeFile,
} from "./volume-backups.js";

/** A run's UTC second, or the date alone for backups taken before stamps had a time. */
const BACKUP_STAMP_RE = /^\d{4}-\d{2}-\d{2}(T\d{2}-\d{2}-\d{2}Z)?$/;

/** A run's files carry this until every one of them is written. */
const PARTIAL_SUFFIX = ".partial";

const MONGO = { prefix: "mongo-", suffix: ".gz" };
const POSTGRES = { prefix: "postgres-", suffix: ".sql" };
const API_ENV = { prefix: "api-env-", suffix: ".env" };
const VOLUME_SUFFIX = ".tar.gz";

const ALL_KINDS = [
  MONGO,
  POSTGRES,
  API_ENV,
  ...VOLUME_BACKUPS.map((v) => ({
    prefix: `${v.fileSuffix}-`,
    suffix: VOLUME_SUFFIX,
  })),
];

export interface BackupFileSet {
  mongoFile: string;
  postgresFile: string;
  /** The install's apps/api/.env: its INSTANCE_SECRET decrypts the dump's credentials. */
  apiEnvFile: string;
  volumeFiles: VolumeFile[];
}

/** `YYYY-MM-DDTHH-MM-SSZ`: sorts chronologically and has no colon for filesystems that reject one. */
export function backupStamp(now = new Date()): string {
  return `${now.toISOString().slice(0, 19).replaceAll(":", "-")}Z`;
}

export function backupFileSet(dir: string, stamp: string): BackupFileSet {
  const name = (kind: { prefix: string; suffix: string }): string =>
    path.join(dir, `${kind.prefix}${stamp}${kind.suffix}`);
  return {
    mongoFile: name(MONGO),
    postgresFile: name(POSTGRES),
    apiEnvFile: name(API_ENV),
    volumeFiles: VOLUME_BACKUPS.map((v) => volumeBackupFile(dir, stamp, v)),
  };
}

export function volumeBackupFile(
  dir: string,
  stamp: string,
  volume: VolumeBackup,
): VolumeFile {
  return {
    volume: volume.volume,
    label: volume.label,
    file: path.join(dir, `${volume.fileSuffix}-${stamp}${VOLUME_SUFFIX}`),
  };
}

export function partialPath(file: string): string {
  return `${file}${PARTIAL_SUFFIX}`;
}

/** The stamp of the newest complete run in `dir`, or undefined when it holds none. */
export function latestBackupStamp(dir: string): string | undefined {
  if (!fs.existsSync(dir)) return undefined;
  const stamps = fs.readdirSync(dir).flatMap((file) =>
    ALL_KINDS.flatMap(({ prefix, suffix }) => {
      if (!file.startsWith(prefix) || !file.endsWith(suffix)) return [];
      const stamp = file.slice(prefix.length, file.length - suffix.length);
      return BACKUP_STAMP_RE.test(stamp) ? [stamp] : [];
    }),
  );
  return stamps.sort().at(-1);
}

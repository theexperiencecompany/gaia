/**
 * The named volumes `gaia backup` archives and `gaia restore` reloads, shared
 * so the two commands can never disagree about a volume's name or file.
 *
 * @module lib/volume-backups
 */

/** A named volume archived next to the database dumps. */
export interface VolumeBackup {
  volume: string;
  /** Archive name prefix: `<fileSuffix>-<date>.tar.gz`. */
  fileSuffix: string;
  label: string;
  /** User data with no other copy: a failed archive fails the backup. */
  userData: boolean;
}

/** One archived (or to-be-restored) volume and its file. */
export interface VolumeFile {
  volume: string;
  label: string;
  file: string;
}

/**
 * Volumes archived via `alpine tar` beyond the database dumps; every name is
 * pinned with `name:` in docker-compose.selfhost.yml. Redis, RabbitMQ and the
 * model cache are transient and intentionally skipped.
 */
export const VOLUME_BACKUPS: readonly VolumeBackup[] = [
  {
    volume: "gaia-selfhost_chroma_data",
    fileSuffix: "chroma_data",
    label: "ChromaDB",
    userData: false,
  },
  {
    volume: "gaia-selfhost_workspace",
    fileSuffix: "workspace",
    label: "Workspace files",
    userData: true,
  },
  {
    volume: "gaia-selfhost_files",
    fileSuffix: "files",
    label: "Uploaded files",
    userData: true,
  },
];

/**
 * Shell run in an alpine container with the volume at /data and the archive
 * dir at /backups. Extracts to a temp dir first and wipes /data only after
 * tar succeeds, so a failed restore keeps the existing data.
 */
export function volumeRestoreScript(archiveName: string): string {
  return `mkdir -p /tmp/restore && tar xzf /backups/${archiveName} -C /tmp/restore && { rm -rf /data/* 2>/dev/null; rm -rf /data/.[!.]* 2>/dev/null || true; } && cp -a /tmp/restore/. /data/ && rm -rf /tmp/restore`;
}

/**
 * What apt is doing during an install, read from the files apt and dpkg
 * write rather than from their output: Docker's install script sends apt's
 * output to /dev/null, so its log has nothing to show for minutes.
 * @module lib/apt-activity
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { formatBytes } from "./byte-size.js";

/** dpkg appends one line per package action; readable by every user. */
const DPKG_LOG = "/var/log/dpkg.log";
/** apt moves each package here once its download finishes. */
const APT_ARCHIVES = "/var/cache/apt/archives";
const POLL_MS = 1000;
/** Below this, formatBytes would print "0 MB". */
const MIN_REPORTED_BYTES = 1e6;

/** `2026-10-18 03:48:40 configure docker-ce:arm64 5:29.9.1 <none>` */
const DPKG_ACTION_RE = /^\S+ \S+ (unpack|configure) ([^:\s]+)/;
const DPKG_ACTIONS: Record<string, string> = {
  unpack: "unpacking",
  configure: "setting up",
};

/** "setting up docker-ce" from one dpkg.log line; null for a line that is not a package step. */
export function describeDpkgLine(line: string): string | null {
  const match = DPKG_ACTION_RE.exec(line);
  if (!match?.[1] || !match[2]) return null;
  return `${DPKG_ACTIONS[match[1]]} ${match[2]}`;
}

function fileSize(file: string): number {
  return fs.existsSync(file) ? fs.statSync(file).size : 0;
}

/** Bytes of the packages apt finished downloading since `since` (ms). */
function downloadedSince(since: number): number {
  if (!fs.existsSync(APT_ARCHIVES)) return 0;
  return fs
    .readdirSync(APT_ARCHIVES)
    .filter((name) => name.endsWith(".deb"))
    .map((name) => fs.statSync(path.join(APT_ARCHIVES, name)))
    .filter((stat) => stat.ctimeMs >= since)
    .reduce((sum, stat) => sum + stat.size, 0);
}

/** The newest package step in dpkg.log past `offset`, and the offset after it. */
function readDpkgSince(offset: number): {
  activity: string | null;
  offset: number;
} {
  const size = fileSize(DPKG_LOG);
  // A rotated log starts again from zero.
  const from = size < offset ? 0 : offset;
  if (size === from) return { activity: null, offset: from };
  const buffer = Buffer.alloc(size - from);
  const fd = fs.openSync(DPKG_LOG, "r");
  try {
    fs.readSync(fd, buffer, 0, buffer.length, from);
  } finally {
    fs.closeSync(fd);
  }
  const lines = buffer.toString().split("\n");
  const activity =
    lines.map(describeDpkgLine).findLast((line) => line !== null) ?? null;
  return { activity, offset: size };
}

/**
 * Report what apt is doing about once a second ("downloading packages: 48 MB",
 * "setting up containerd.io") until the returned stop function is called.
 */
export function watchAptActivity(
  onActivity: (activity: string) => void,
): () => void {
  const startedAt = Date.now();
  let offset = fileSize(DPKG_LOG);
  let downloaded = 0;
  const timer = setInterval(() => {
    const dpkg = readDpkgSince(offset);
    offset = dpkg.offset;
    if (dpkg.activity) {
      onActivity(dpkg.activity);
      return;
    }
    const total = downloadedSince(startedAt);
    if (total >= MIN_REPORTED_BYTES && total > downloaded) {
      downloaded = total;
      onActivity(`downloading packages: ${formatBytes(total)}`);
    }
  }, POLL_MS);
  return () => clearInterval(timer);
}

/**
 * Download sizes as every progress line shows them.
 * @module lib/byte-size
 */

const BINARY_UNITS = { KiB: 1024, MiB: 1024 ** 2, GiB: 1024 ** 3 } as const;

/** 1.3 GB, 412 MB: decimal units, as registries and `docker images` show sizes. */
export function formatBytes(bytes: number): string {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  return `${Math.round(bytes / 1e6)} MB`;
}

/**
 * "410 / 660 MB", "0.4 / 1.3 GB", "31 / ~72 MB": both numbers in the total's
 * unit, the total marked when it is still an estimate.
 */
export function formatByteProgress(
  done: number,
  total: number,
  estimated: boolean,
): string {
  const [divisor, unit, digits] =
    total >= 1e9
      ? [1e9, "GB", 1]
      : total >= 1e6
        ? [1e6, "MB", 0]
        : [1e3, "KB", 0];
  const show = (bytes: number) => (bytes / divisor).toFixed(digits);
  return `${show(done)} / ${estimated ? "~" : ""}${show(total)} ${unit}`;
}

/** Bytes in a size git prints, e.g. "52.18 MiB". */
export function parseBinarySize(size: string): number | null {
  const match = /^([\d.]+)\s*(KiB|MiB|GiB)$/.exec(size.trim());
  if (!match?.[1] || !match[2]) return null;
  return Number(match[1]) * BINARY_UNITS[match[2] as keyof typeof BINARY_UNITS];
}

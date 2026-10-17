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

/** Bytes in a size git prints, e.g. "52.18 MiB". */
export function parseBinarySize(size: string): number | null {
  const match = /^([\d.]+)\s*(KiB|MiB|GiB)$/.exec(size.trim());
  if (!match?.[1] || !match[2]) return null;
  return Number(match[1]) * BINARY_UNITS[match[2] as keyof typeof BINARY_UNITS];
}

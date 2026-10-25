/**
 * Downloading a release asset and proving it is the one published: the
 * gaia-connect binary and the self-host bundle both go through here.
 * @module lib/download
 */

import { createHash } from "node:crypto";

/** Bytes received so far, of the size the server announced (null when it named none). */
export interface DownloadProgress {
  received: number;
  total: number | null;
}

/** A download the server refused, with its HTTP status. */
export class DownloadError extends Error {
  constructor(
    readonly status: number,
    readonly url: string,
    statusText: string,
  ) {
    super(`Download failed (${status} ${statusText}): ${url}`);
    this.name = "DownloadError";
  }
}

/**
 * Fetch a URL into memory, reporting each chunk as it arrives.
 * @throws DownloadError naming the status and URL when the server does not answer 2xx.
 */
export async function downloadBytes(
  url: string,
  onProgress?: (progress: DownloadProgress) => void,
): Promise<Buffer> {
  const response = await fetch(url);
  if (!response.ok || !response.body) {
    throw new DownloadError(response.status, url, response.statusText);
  }
  const length = Number(response.headers.get("content-length"));
  const total = Number.isFinite(length) && length > 0 ? length : null;
  const chunks: Uint8Array[] = [];
  let received = 0;
  for await (const chunk of response.body) {
    chunks.push(chunk);
    received += chunk.byteLength;
    onProgress?.({ received, total });
  }
  return Buffer.concat(chunks);
}

/**
 * Pull one asset's digest out of a `sha256sum` file (`<hex>  <name>` per line).
 * @throws Error naming the checksum file when it lists no such asset.
 */
export function digestForAsset(
  checksums: string,
  assetName: string,
  checksumSource: string,
): string {
  for (const line of checksums.split("\n")) {
    const [digest, ...rest] = line.trim().split(/\s+/);
    const name = rest.join(" ").replace(/^\*/, "");
    if (name === assetName && digest !== undefined) return digest.toLowerCase();
  }
  throw new Error(`${checksumSource} has no entry for ${assetName}.`);
}

/** @throws Error when the bytes are not the ones the checksum names. */
export function assertDigest(
  bytes: Buffer,
  expected: string,
  assetName: string,
): void {
  const actual = createHash("sha256").update(bytes).digest("hex");
  if (actual !== expected) {
    throw new Error(
      `Checksum mismatch for ${assetName}: expected ${expected}, got ${actual}. ` +
        "Refusing to use the download.",
    );
  }
}

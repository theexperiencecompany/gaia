// Downloads, verifies and caches the `gaia-connect` binary in ~/.gaia/bin.

import { createHash } from "node:crypto";
import * as fs from "node:fs/promises";
import * as path from "node:path";
import {
  assetUrl,
  binaryPath,
  CHECKSUMS_ASSET,
  CONNECT_RELEASE_TAG,
  resolveAssetName,
} from "./asset.js";

async function fetchBytes(url: string): Promise<Buffer> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(
      `Download failed (${response.status} ${response.statusText}): ${url}`,
    );
  }
  return Buffer.from(await response.arrayBuffer());
}

/**
 * Pull one asset's digest out of a `sha256sum` file (`<hex>  <name>` per line).
 */
export function digestForAsset(checksums: string, assetName: string): string {
  for (const line of checksums.split("\n")) {
    const [digest, ...rest] = line.trim().split(/\s+/);
    const name = rest.join(" ").replace(/^\*/, "");
    if (name === assetName && digest !== undefined) return digest.toLowerCase();
  }
  throw new Error(
    `${CHECKSUMS_ASSET} on release ${CONNECT_RELEASE_TAG} has no entry for ${assetName}.`,
  );
}

function sha256(bytes: Buffer): string {
  return createHash("sha256").update(bytes).digest("hex");
}

async function exists(file: string): Promise<boolean> {
  try {
    await fs.access(file);
    return true;
  } catch {
    return false;
  }
}

/**
 * Path to a verified `gaia-connect` binary, downloading it on first use.
 * Any tampering or transport failure aborts loudly instead of running bytes we
 * cannot vouch for.
 */
export async function ensureConnectBinary(
  platform: string,
  arch: string,
): Promise<string> {
  const target = binaryPath(platform);
  if (await exists(target)) return target;

  const assetName = resolveAssetName(platform, arch);
  console.info(`Downloading gaia-connect (${CONNECT_RELEASE_TAG})...`);

  const [binary, checksums] = await Promise.all([
    fetchBytes(assetUrl(assetName)),
    fetchBytes(assetUrl(CHECKSUMS_ASSET)).then((b) => b.toString("utf-8")),
  ]);

  const expected = digestForAsset(checksums, assetName);
  const actual = sha256(binary);
  if (actual !== expected) {
    throw new Error(
      `Checksum mismatch for ${assetName}: expected ${expected}, got ${actual}. ` +
        `Refusing to run the download.`,
    );
  }

  await fs.mkdir(path.dirname(target), { recursive: true });
  const temp = `${target}.${process.pid}.tmp`;
  try {
    await fs.writeFile(temp, binary);
    // Owner-only: the binary is fetched for, and run by, this user alone.
    if (platform !== "win32") await fs.chmod(temp, 0o700);
    await fs.rename(temp, target);
  } catch (error) {
    await fs.rm(temp, { force: true });
    throw error;
  }
  return target;
}

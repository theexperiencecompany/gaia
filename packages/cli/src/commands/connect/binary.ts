// Downloads, verifies and caches the `gaia-connect` binary in ~/.gaia/bin.

import * as fs from "node:fs/promises";
import * as path from "node:path";
import {
  assertDigest,
  digestForAsset,
  downloadBytes,
} from "../../lib/download.js";
import {
  assetUrl,
  binaryPath,
  CHECKSUMS_ASSET,
  CONNECT_RELEASE_TAG,
  resolveAssetName,
} from "./asset.js";

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
  console.info(`Downloading gaia-connect (${CONNECT_RELEASE_TAG})…`);

  const [binary, checksums] = await Promise.all([
    downloadBytes(assetUrl(assetName)),
    downloadBytes(assetUrl(CHECKSUMS_ASSET)).then((b) => b.toString("utf-8")),
  ]);

  assertDigest(
    binary,
    digestForAsset(
      checksums,
      assetName,
      `${CHECKSUMS_ASSET} on release ${CONNECT_RELEASE_TAG}`,
    ),
    assetName,
  );

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

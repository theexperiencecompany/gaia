// Release layout for the `gaia-connect` Go tool. CI publishes these assets on
// the CLI's own release-please tag, so the CLI version pins the binary version.

import * as os from "node:os";
import * as path from "node:path";
import { CLI_VERSION } from "../../lib/version.js";

const RELEASE_BASE =
  "https://github.com/theexperiencecompany/gaia/releases/download";

export const CONNECT_RELEASE_TAG = `cli-v${CLI_VERSION}`;
export const CHECKSUMS_ASSET = "gaia-connect-SHA256SUMS";

const ASSETS_BY_TARGET = {
  "darwin-arm64": "gaia-connect-darwin-arm64",
  "darwin-x64": "gaia-connect-darwin-amd64",
  "linux-x64": "gaia-connect-linux-amd64",
  "linux-arm64": "gaia-connect-linux-arm64",
  "win32-x64": "gaia-connect-windows-amd64.exe",
} as const;

type Target = keyof typeof ASSETS_BY_TARGET;

/** Release asset for this OS/CPU. Throws (no fallback) on an unsupported pair. */
export function resolveAssetName(platform: string, arch: string): string {
  const asset = ASSETS_BY_TARGET[`${platform}-${arch}` as Target];
  if (asset === undefined) {
    throw new Error(
      `gaia connect is not available for ${platform}/${arch}. ` +
        `Supported: ${Object.keys(ASSETS_BY_TARGET).join(", ")}.`,
    );
  }
  return asset;
}

export function assetUrl(assetName: string): string {
  return `${RELEASE_BASE}/${CONNECT_RELEASE_TAG}/${assetName}`;
}

/** Cache location — versioned so a CLI upgrade never reuses an old binary. */
export function binaryPath(platform: string): string {
  const suffix = platform === "win32" ? ".exe" : "";
  return path.join(
    os.homedir(),
    ".gaia",
    "bin",
    `gaia-connect-${CLI_VERSION}${suffix}`,
  );
}

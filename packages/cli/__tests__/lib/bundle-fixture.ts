// Builds self-host bundles the way release.sh selfhost-bundle does, and serves
// them through a stubbed fetch the way a GitHub Release does.

import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import { vi } from "vitest";
import { BUNDLE_MANIFEST } from "../../src/lib/selfhost-bundle.js";

export function writeFile(dir: string, file: string, content: string): void {
  fs.mkdirSync(path.dirname(path.join(dir, file)), { recursive: true });
  fs.writeFileSync(path.join(dir, file), content);
}

/** A gaia-selfhost tarball of these files plus a manifest naming them. */
export function buildBundle(
  workDir: string,
  version: string,
  files: Record<string, string>,
): Buffer {
  const src = fs.mkdtempSync(path.join(workDir, "bundle-src-"));
  for (const [file, content] of Object.entries(files)) {
    writeFile(src, file, content);
  }
  const listed = [...Object.keys(files), BUNDLE_MANIFEST].sort();
  writeFile(src, BUNDLE_MANIFEST, JSON.stringify({ version, files: listed }));
  const archive = path.join(workDir, `bundle-${version}.tar.gz`);
  execFileSync("tar", ["-czf", archive, "-C", src, ...listed]);
  return fs.readFileSync(archive);
}

export function sha256(bytes: Buffer): string {
  return createHash("sha256").update(bytes).digest("hex");
}

/**
 * Serve bundles by release tag at their GitHub Release URLs, each with a
 * matching .sha256; an unknown release answers 404. Returns the URLs asked for.
 */
export function serveBundles(bundles: Record<string, Buffer>): string[] {
  const requested: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      requested.push(url);
      const match = /\/gaia-selfhost-([^/]+)\.tar\.gz(\.sha256)?$/.exec(url);
      const bundle = match?.[1] ? bundles[`v${match[1]}`] : undefined;
      if (!match || !bundle) return new Response("Not Found", { status: 404 });
      if (match[2]) {
        return new Response(
          `${sha256(bundle)}  gaia-selfhost-${match[1]}.tar.gz\n`,
        );
      }
      return new Response(new Uint8Array(bundle), {
        headers: { "content-length": String(bundle.length) },
      });
    }),
  );
  return requested;
}

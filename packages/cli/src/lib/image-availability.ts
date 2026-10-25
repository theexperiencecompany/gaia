/**
 * Whether GAIA's images exist in the registry for a tag and this computer's
 * CPU, asked of GHCR directly so it works before Docker is usable.
 * @module lib/image-availability
 */

import * as os from "node:os";
import type { SelfhostBot } from "./bots.js";

const REGISTRY = "https://ghcr.io";
const NAMESPACE = "theexperiencecompany";
const REQUEST_TIMEOUT_MS = 8_000;

/** The repos every self-host release must publish. */
const APP_IMAGES = ["gaia", "gaia-web"] as const;

const MANIFEST_ACCEPT = [
  "application/vnd.oci.image.index.v1+json",
  "application/vnd.docker.distribution.manifest.list.v2+json",
  "application/vnd.oci.image.manifest.v1+json",
  "application/vnd.docker.distribution.manifest.v2+json",
].join(",");

/** Docker's name for this machine's CPU, as image manifests list it. */
export function dockerArch(arch: string = os.arch()): string {
  return arch === "x64" ? "amd64" : arch;
}

interface ManifestIndex {
  manifests?: { platform?: { architecture?: string; os?: string } }[];
  config?: { digest: string };
}

async function registryToken(repo: string): Promise<string> {
  const res = await fetch(
    `${REGISTRY}/token?scope=repository:${NAMESPACE}/${repo}:pull`,
    { signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) },
  );
  if (!res.ok)
    throw new Error(`GHCR token request answered HTTP ${res.status}`);
  return ((await res.json()) as { token: string }).token;
}

async function registryGet(
  repo: string,
  pathPart: string,
  token: string,
): Promise<Response> {
  return fetch(`${REGISTRY}/v2/${NAMESPACE}/${repo}/${pathPart}`, {
    headers: { Authorization: `Bearer ${token}`, Accept: MANIFEST_ACCEPT },
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
}

/** The CPU architectures one image tag is published for; empty when the tag does not exist. */
export async function publishedArchitectures(
  repo: string,
  tag: string,
): Promise<string[]> {
  const token = await registryToken(repo);
  const res = await registryGet(repo, `manifests/${tag}`, token);
  if (res.status === 404) return [];
  if (!res.ok) {
    throw new Error(`GHCR answered HTTP ${res.status} for ${repo}:${tag}`);
  }
  const manifest = (await res.json()) as ManifestIndex;
  if (manifest.manifests) {
    return manifest.manifests
      .map((m) => m.platform?.architecture)
      .filter((a): a is string => Boolean(a) && a !== "unknown");
  }
  if (!manifest.config) return [];
  // A single-platform image names its CPU only in its config blob.
  const config = await registryGet(
    repo,
    `blobs/${manifest.config.digest}`,
    token,
  );
  if (!config.ok) {
    throw new Error(
      `GHCR answered HTTP ${config.status} for ${repo}:${tag}'s config`,
    );
  }
  const { architecture } = (await config.json()) as { architecture?: string };
  return architecture ? [architecture] : [];
}

/** Why a release cannot be installed on this computer, or null when it can. */
export type ReleaseImageGap =
  | { kind: "not-published"; image: string }
  | { kind: "wrong-cpu"; image: string; arch: string };

/** The first of a release's images (bots included) missing for this CPU; null when all exist. */
export async function findReleaseImageGap(
  tag: string,
  bots: readonly SelfhostBot[] = [],
  arch: string = dockerArch(),
): Promise<ReleaseImageGap | null> {
  const repos = [...APP_IMAGES, ...bots.map((bot) => `gaia-bot-${bot}`)];
  for (const repo of repos) {
    const archs = await publishedArchitectures(repo, tag);
    if (archs.length === 0)
      return { kind: "not-published", image: `${repo}:${tag}` };
    if (!archs.includes(arch))
      return { kind: "wrong-cpu", image: `${repo}:${tag}`, arch };
  }
  return null;
}

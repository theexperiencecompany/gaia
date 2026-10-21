/**
 * The size of an image pull before it starts, read from the registries'
 * manifests: Docker's own progress names a layer's size only once that layer
 * begins downloading, so a total summed from it keeps growing for minutes.
 * Layers are keyed by the short id Docker's progress events use.
 * @module lib/pull-size
 */

import { execa } from "execa";
import { dockerArch } from "./image-availability.js";

const REQUEST_TIMEOUT_MS = 8_000;
const DOCKER_HUB = "docker.io";
const DOCKER_HUB_API = "registry-1.docker.io";
/** Docker's progress names a layer by the first 12 hex digits of its digest. */
const SHORT_ID_LENGTH = 12;

const MANIFEST_ACCEPT = [
  "application/vnd.oci.image.index.v1+json",
  "application/vnd.docker.distribution.manifest.list.v2+json",
  "application/vnd.oci.image.manifest.v1+json",
  "application/vnd.docker.distribution.manifest.v2+json",
].join(",");

export interface ImageRef {
  /** The registry's API host, e.g. ghcr.io or registry-1.docker.io. */
  host: string;
  repository: string;
  /** A tag or a digest. */
  reference: string;
}

/** "mongo:8" → Docker Hub's library/mongo at 8; "ghcr.io/a/b:v1" → ghcr.io's a/b at v1. */
export function parseImageRef(ref: string): ImageRef {
  const [name = ref, digest] = ref.split("@");
  const slash = name.indexOf("/");
  const first = slash === -1 ? "" : name.slice(0, slash);
  const isRegistry =
    first.includes(".") || first.includes(":") || first === "localhost";
  const registry = isRegistry ? first : DOCKER_HUB;
  let path = isRegistry ? name.slice(slash + 1) : name;
  const colon = path.lastIndexOf(":");
  const tag = colon === -1 ? "latest" : path.slice(colon + 1);
  if (colon !== -1) path = path.slice(0, colon);
  if (registry === DOCKER_HUB && !path.includes("/")) path = `library/${path}`;
  return {
    host: registry === DOCKER_HUB ? DOCKER_HUB_API : registry,
    repository: path,
    reference: digest ?? tag,
  };
}

/** The token URL a registry's `WWW-Authenticate: Bearer realm=...` challenge names. */
export function tokenUrl(challenge: string): string | null {
  if (!challenge.startsWith("Bearer ")) return null;
  const params = Object.fromEntries(
    [...challenge.matchAll(/(\w+)="([^"]*)"/g)].map((m) => [m[1], m[2]]),
  );
  if (!params.realm) return null;
  let url: URL;
  try {
    url = new URL(params.realm);
  } catch (cause) {
    throw new Error(`registry token realm is not a URL: ${params.realm}`, {
      cause,
    });
  }
  for (const key of ["service", "scope"]) {
    if (params[key]) url.searchParams.set(key, params[key]);
  }
  return url.toString();
}

interface Manifest {
  manifests?: {
    digest: string;
    platform?: { architecture?: string; os?: string };
  }[];
  layers?: { digest: string; size: number }[];
}

async function getManifest(
  image: ImageRef,
  reference: string,
  token: string | null,
): Promise<Response> {
  return fetch(
    `https://${image.host}/v2/${image.repository}/manifests/${reference}`,
    {
      headers: {
        Accept: MANIFEST_ACCEPT,
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    },
  );
}

/** A pull token for the image when its registry asks for one; null when it does not. */
async function pullToken(image: ImageRef): Promise<string | null> {
  const probe = await getManifest(image, image.reference, null);
  if (probe.status !== 401) return null;
  const url = tokenUrl(probe.headers.get("www-authenticate") ?? "");
  if (!url) {
    throw new Error(`${image.host} asked for credentials it did not name`);
  }
  const res = await fetch(url, {
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
  if (!res.ok) {
    throw new Error(`${image.host} token request answered HTTP ${res.status}`);
  }
  const body = (await res.json()) as { token?: string; access_token?: string };
  return body.token ?? body.access_token ?? null;
}

async function readManifest(
  image: ImageRef,
  reference: string,
  token: string | null,
): Promise<Manifest> {
  const res = await getManifest(image, reference, token);
  if (!res.ok) {
    throw new Error(
      `${image.host} answered HTTP ${res.status} for ${image.repository}@${reference}`,
    );
  }
  return (await res.json()) as Manifest;
}

/**
 * The compressed size of each layer of one image for this computer's CPU.
 * @throws Error when the registry cannot be read or has no image for this CPU.
 */
export async function imageLayerSizes(
  ref: string,
  arch: string = dockerArch(),
): Promise<Map<string, number>> {
  const image = parseImageRef(ref);
  const token = await pullToken(image);
  let manifest = await readManifest(image, image.reference, token);
  if (manifest.manifests) {
    const forHere = manifest.manifests.find(
      (m) => m.platform?.os === "linux" && m.platform.architecture === arch,
    );
    if (!forHere) throw new Error(`${ref} has no linux/${arch} image`);
    manifest = await readManifest(image, forHere.digest, token);
  }
  return new Map(
    (manifest.layers ?? []).map((layer) => [
      layer.digest.replace(/^sha256:/, "").slice(0, SHORT_ID_LENGTH),
      layer.size,
    ]),
  );
}

/** Every layer of these images, each counted once though images share it. */
async function pullLayerSizes(
  refs: readonly string[],
): Promise<Map<string, number>> {
  const sizes = await Promise.all(refs.map((ref) => imageLayerSizes(ref)));
  return new Map(sizes.flatMap((layers) => [...layers]));
}

/** What a pull will download: each layer's size, or why that could not be read (the bar then estimates). */
export type PullSize =
  | { layers: ReadonlyMap<string, number> }
  | { unknown: string };

async function missingImages(refs: readonly string[]): Promise<string[]> {
  const found = await Promise.all(
    refs.map((ref) =>
      execa("docker", ["image", "inspect", ref], { reject: false }),
    ),
  );
  return refs.filter((_, i) => found[i]?.exitCode !== 0);
}

/** The services compose runs for these files, env and profiles, with their images. */
export type ComposeServices = Record<string, { image?: string }>;

/**
 * Read the services compose would run, from `docker compose config`.
 * @throws Error saying compose couldn't read the setup files, with its own reason.
 */
export async function readComposeServices(
  cwd: string,
  composeArgs: readonly string[],
  env: Record<string, string> | undefined,
): Promise<ComposeServices> {
  const result = await execa(
    "docker",
    ["compose", ...composeArgs, "config", "--format", "json"],
    { cwd, env, reject: false },
  );
  if (result.failed) {
    const reason = result.stderr.trim().split("\n").at(-1) ?? "";
    throw new Error(
      `Docker Compose couldn't read GAIA's setup files in ${cwd}: ${reason}`,
    );
  }
  return (JSON.parse(result.stdout) as { services: ComposeServices }).services;
}

/**
 * Measure what `docker compose` is about to pull for these services (all
 * when none are named): the images not on this computer, or every one when
 * the pull refreshes them all. Never fails the pull it measures: an unreadable
 * registry turns the total into an estimate, and the reason goes to the log.
 */
export async function measurePull(
  services: ComposeServices,
  options: { only?: readonly string[]; always: boolean },
): Promise<PullSize> {
  try {
    const wanted = options.only && new Set(options.only);
    const refs = [
      ...new Set(
        Object.entries(services)
          .filter(([name]) => !wanted || wanted.has(name))
          .flatMap(([, service]) => (service.image ? [service.image] : [])),
      ),
    ];
    const pulled = options.always ? refs : await missingImages(refs);
    return { layers: await pullLayerSizes(pulled) };
  } catch (error) {
    return { unknown: (error as Error).message };
  }
}

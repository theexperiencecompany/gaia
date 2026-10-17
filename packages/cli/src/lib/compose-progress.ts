/**
 * Turn `docker compose --progress json` events into what a person needs to
 * see: which phase GAIA is in (downloading, building, starting) with a size
 * or step count and a percentage, plus a short list of finished steps.
 * Pure, so every screen and test reads the same numbers.
 * @module lib/compose-progress
 */

import { serviceName } from "./display-names.js";

/** One line of `docker compose --progress json` output, as far as we read it. */
export interface ComposeEvent {
  id?: string;
  parent_id?: string;
  status?: string;
  text?: string;
  details?: string;
  current?: number;
  total?: number;
  error?: boolean;
  message?: string;
  /** BuildKit vertices: one per build step, `[stage n/m] RUN ...`. */
  vertexes?: { digest: string; name?: string; completed?: string }[];
}

interface Layer {
  current: number;
  total: number;
  done: boolean;
}

type ImageState = "downloading" | "building" | "ready";

export interface ComposeProgressState {
  /** Image ref -> where it stands. */
  images: Map<string, ImageState>;
  layers: Map<string, Layer>;
  /** Build steps (BuildKit vertices named `[n/m] ...`) -> completed yet. */
  steps: Map<string, { name: string; done: boolean }>;
  /** Service -> started yet. */
  containers: Map<string, boolean>;
  /** Finished steps worth showing, newest last. */
  finished: string[];
  /** Error messages compose reported, in order. */
  errors: string[];
  /** Highest download percentage shown so far, so the bar never moves back. */
  downloadPercent: number;
}

export function createComposeProgress(): ComposeProgressState {
  return {
    images: new Map(),
    layers: new Map(),
    steps: new Map(),
    containers: new Map(),
    finished: [],
    errors: [],
    downloadPercent: 0,
  };
}

const IMAGE_PREFIX = "Image ";
const CONTAINER_PREFIX = "Container ";
const BUILD_STEP_RE = /^\[[^\]]*\d+\/\d+\]/;
/** Compose names containers <project>-<service>-<n>. */
const CONTAINER_NAME_RE = /^gaia-(?:selfhost|dev)-(.+)-\d+$/;

/** The last path segment of an image ref, e.g. gaia-web:v0.7.0. */
export function shortImageName(ref: string): string {
  return ref.slice(ref.lastIndexOf("/") + 1);
}

function containerService(id: string): string {
  const name = id.slice(CONTAINER_PREFIX.length);
  return CONTAINER_NAME_RE.exec(name)?.[1] ?? name;
}

function applyImageEvent(state: ComposeProgressState, e: ComposeEvent): void {
  const ref = (e.id ?? "").slice(IMAGE_PREFIX.length);
  if (e.status === "Error") {
    state.errors.push(`${ref}: ${e.details ?? e.text ?? "error"}`);
    return;
  }
  const previous = state.images.get(ref);
  if (previous === "ready") return;
  if (e.text === "Pulled" || e.text === "Built") {
    state.finished.push(
      `${e.text === "Built" ? "Built" : "Downloaded"} ${shortImageName(ref)}`,
    );
    state.images.set(ref, "ready");
  } else {
    state.images.set(ref, e.text === "Building" ? "building" : "downloading");
  }
}

function applyLayerEvent(state: ComposeProgressState, e: ComposeEvent): void {
  const id = e.id ?? "";
  const layer = state.layers.get(id) ?? { current: 0, total: 0, done: false };
  if (e.text === "Downloading" && e.total) {
    layer.total = e.total;
    layer.current = e.current ?? layer.current;
  }
  if (e.text === "Download complete" || e.text === "Pull complete") {
    layer.done = true;
    layer.current = layer.total;
  }
  state.layers.set(id, layer);
}

function applyContainerEvent(
  state: ComposeProgressState,
  e: ComposeEvent,
): void {
  const service = containerService(e.id ?? "");
  const started = e.text === "Started" || e.text === "Healthy";
  if (e.status === "Error") {
    state.errors.push(`${service}: ${e.details ?? e.text ?? "error"}`);
  }
  if (started && !state.containers.get(service)) {
    state.finished.push(`Started ${serviceName(service)}`);
  }
  state.containers.set(
    service,
    state.containers.get(service) === true || started,
  );
}

/** Fold one compose event into the progress state (mutates and returns it). */
export function applyComposeEvent(
  state: ComposeProgressState,
  e: ComposeEvent,
): ComposeProgressState {
  if (e.error && e.message) state.errors.push(e.message);
  for (const vertex of e.vertexes ?? []) {
    const known = state.steps.get(vertex.digest);
    const name = vertex.name ?? known?.name;
    if (!name || !BUILD_STEP_RE.test(name)) continue;
    state.steps.set(vertex.digest, {
      name,
      done: known?.done === true || Boolean(vertex.completed),
    });
  }
  const id = e.id ?? "";
  if (id.startsWith(IMAGE_PREFIX)) applyImageEvent(state, e);
  else if (id.startsWith(CONTAINER_PREFIX)) applyContainerEvent(state, e);
  else if (e.parent_id?.startsWith(IMAGE_PREFIX)) applyLayerEvent(state, e);
  return state;
}

/** 1.3 GB, 412 MB: decimal units, as registries and `docker images` show sizes. */
export function formatBytes(bytes: number): string {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  return `${Math.round(bytes / 1e6)} MB`;
}

export interface ComposePhase {
  /** One line naming the phase and how far along it is. */
  label: string;
  /** 0-100 for the bar. */
  percent: number;
}

/** Where a compose run is, for the progress line and bar. */
export function describeComposeProgress(
  state: ComposeProgressState,
): ComposePhase | null {
  const steps = [...state.steps.values()];
  const stepsDone = steps.filter((s) => s.done).length;
  if (steps.length > 0 && stepsDone < steps.length) {
    return {
      label: `Building GAIA from source: step ${stepsDone + 1} of ${steps.length}`,
      percent: Math.floor((stepsDone / steps.length) * 100),
    };
  }

  const images = [...state.images.values()];
  if (images.includes("building") && !images.includes("downloading")) {
    return {
      label: "Building GAIA from source: saving the images",
      percent: 99,
    };
  }
  if (images.includes("downloading")) {
    const layers = [...state.layers.values()].filter((l) => l.total > 0);
    const total = layers.reduce((sum, l) => sum + l.total, 0);
    const current = layers.reduce((sum, l) => sum + l.current, 0);
    const ready = images.filter((image) => image === "ready").length;
    state.downloadPercent = Math.max(
      state.downloadPercent,
      total > 0 ? Math.floor((current / total) * 100) : 0,
    );
    const size =
      total > 0
        ? `${formatBytes(current)} of ${formatBytes(total)}`
        : "starting";
    return {
      label: `Downloading GAIA: ${size} (${ready} of ${images.length} images ready)`,
      percent: state.downloadPercent,
    };
  }

  const containers = [...state.containers.values()];
  if (containers.length > 0) {
    const started = containers.filter(Boolean).length;
    return {
      label: `Starting GAIA: ${started} of ${containers.length} services started`,
      percent: Math.floor((started / containers.length) * 100),
    };
  }
  return null;
}

/**
 * Turn `docker compose --progress json` events into what a person needs to
 * see: which phase GAIA is in (downloading, building, starting) with a size
 * or step count and a percentage, plus a short list of finished steps.
 * Pure, so every screen and test reads the same numbers.
 * @module lib/compose-progress
 */

import { formatBytes } from "./byte-size.js";
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
  /** Service -> up yet (started by this run, or already running). */
  containers: Map<string, boolean>;
  /** Services this run started; an already-running one is not among them. */
  started: Set<string>;
  /** Service -> stopped yet, for `down`; in the order they began to stop. */
  stopping: Map<string, boolean>;
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
    started: new Set(),
    stopping: new Map(),
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
/** `down` stops a running container and only removes one already stopped. */
const STOP_BEGUN = new Set(["Stopping", "Removing"]);
const STOP_DONE = new Set(["Stopped", "Removed"]);
/** Services a stop line names before it counts the rest. */
const NAMED_WAITING = 2;

/** The last path segment of an image ref, e.g. gaia-web:v0.7.0. */
function shortImageName(ref: string): string {
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
  const text = e.text ?? "";
  if (STOP_BEGUN.has(text) || STOP_DONE.has(text)) {
    state.stopping.set(
      service,
      state.stopping.get(service) === true || STOP_DONE.has(text),
    );
    return;
  }
  // "Running": compose found it up already; "Healthy": a dependency check passed.
  const up = ["Started", "Running", "Healthy"].includes(e.text ?? "");
  if (e.status === "Error") {
    state.errors.push(`${service}: ${e.details ?? e.text ?? "error"}`);
  }
  if (e.text === "Started" && !state.started.has(service)) {
    state.started.add(service);
    state.finished.push(`Started ${serviceName(service)}`);
  }
  state.containers.set(service, state.containers.get(service) === true || up);
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

export interface ComposePhase {
  /** One line naming the phase and how far along it is. */
  label: string;
  /** 0-100 for the bar. */
  percent: number;
}

/** A download bar stops short of full until every image is ready. */
const MAX_DOWNLOAD_PERCENT = 99;

/**
 * Bytes downloaded, and a percentage over every layer of the pull. Compose
 * names a layer before it tells its size, so a layer without one counts as
 * the average size of those that have one; the total only grows as layers
 * report, and a bare "x of y" would claim a y that is not the real total.
 */
function estimateDownload(state: ComposeProgressState): {
  downloaded: number;
  percent: number;
} {
  const layers = [...state.layers.values()];
  const sized = layers.filter((l) => l.total > 0);
  const downloaded = sized.reduce((sum, l) => sum + l.current, 0);
  if (sized.length === 0) return { downloaded, percent: 0 };
  const average = sized.reduce((sum, l) => sum + l.total, 0) / sized.length;
  const unsized = layers.filter((l) => l.total === 0);
  const total =
    sized.reduce((sum, l) => sum + l.total, 0) + unsized.length * average;
  const done = downloaded + unsized.filter((l) => l.done).length * average;
  return {
    downloaded,
    percent: Math.min(MAX_DOWNLOAD_PERCENT, Math.floor((done / total) * 100)),
  };
}

/** "Stopping GAIA: waiting on RabbitMQ, MongoDB and 1 more (3 of 6 stopped)". */
function describeStop(stopping: Map<string, boolean>): ComposePhase {
  const waiting = [...stopping].filter(([, done]) => !done);
  const stopped = stopping.size - waiting.length;
  const named = waiting
    .slice(0, NAMED_WAITING)
    .map(([service]) => serviceName(service));
  const rest = waiting.length - named.length;
  const counted = `${stopped} of ${stopping.size} stopped`;
  const percent = Math.floor((stopped / stopping.size) * 100);
  if (waiting.length === 0) {
    return { label: `Stopping GAIA: ${counted}`, percent };
  }
  const names =
    rest > 0 ? `${named.join(", ")} and ${rest} more` : named.join(" and ");
  return {
    label: `Stopping GAIA: waiting on ${names} (${counted})`,
    percent,
  };
}

/** Where a compose run is, for the progress line and bar. */
export function describeComposeProgress(
  state: ComposeProgressState,
): ComposePhase | null {
  if (state.stopping.size > 0) return describeStop(state.stopping);
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
    const ready = images.filter((image) => image === "ready").length;
    const { downloaded, percent } = estimateDownload(state);
    state.downloadPercent = Math.max(state.downloadPercent, percent);
    const size =
      downloaded > 0 ? `${formatBytes(downloaded)} so far` : "starting";
    return {
      label: `Downloading GAIA's images: ${size} (${ready} of ${images.length} ready)`,
      percent: state.downloadPercent,
    };
  }

  const containers = [...state.containers.values()];
  if (containers.length > 0) {
    const started = containers.filter(Boolean).length;
    return {
      label: `Starting GAIA: ${started} of ${containers.length} services up`,
      percent: Math.floor((started / containers.length) * 100),
    };
  }
  return null;
}

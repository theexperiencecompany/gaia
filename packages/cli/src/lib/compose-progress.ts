/**
 * Turn `docker compose --progress json` events into what a person needs to
 * see: which phase GAIA is in (downloading, building, starting) with a size
 * or step count and a percentage, plus a short list of finished steps.
 * Pure, so every screen and test reads the same numbers.
 * @module lib/compose-progress
 */

import { formatByteProgress, formatBytes } from "./byte-size.js";
import { serviceName } from "./display-names.js";
import type { ProgressAmount } from "./progress.js";

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
  /** The image ref this layer is being pulled for. */
  image: string;
  current: number;
  total: number;
  done: boolean;
  /** Already on this computer: nothing to download. */
  present: boolean;
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
  /** Services compose is waiting on to pass their health check before it starts the next. */
  awaitingHealth: Set<string>;
  /** Service -> stopped yet, for `down`; in the order they began to stop. */
  stopping: Map<string, boolean>;
  /** Finished steps worth showing, newest last. */
  finished: string[];
  /** Error messages compose reported, in order. */
  errors: string[];
  /** Layer short id -> size, from the registries before the pull began; empty when unknown. */
  expectedLayers: ReadonlyMap<string, number>;
  /** Largest estimated download total shown so far, so the total never shrinks. */
  downloadTotal: number;
}

export function createComposeProgress(
  expectedLayers: ReadonlyMap<string, number> = new Map(),
): ComposeProgressState {
  return {
    images: new Map(),
    layers: new Map(),
    steps: new Map(),
    containers: new Map(),
    started: new Set(),
    awaitingHealth: new Set(),
    stopping: new Map(),
    finished: [],
    errors: [],
    expectedLayers,
    downloadTotal: 0,
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
  const layer = state.layers.get(id) ?? {
    image: (e.parent_id ?? "").slice(IMAGE_PREFIX.length),
    current: 0,
    total: 0,
    done: false,
    present: false,
  };
  if (e.text === "Downloading" && e.total) {
    layer.total = e.total;
    layer.current = e.current ?? layer.current;
  }
  if (e.text === "Already exists") layer.present = true;
  if (
    e.text === "Download complete" ||
    e.text === "Pull complete" ||
    e.text === "Already exists"
  ) {
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
  // "Waiting": compose holds what depends on this service until its health check passes.
  if (e.text === "Waiting") state.awaitingHealth.add(service);
  if (e.text === "Healthy") state.awaitingHealth.delete(service);
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

/** What compose is doing, for a heading above the phase line. */
export type ComposeStage =
  | "building"
  | "downloading"
  | "unpacking"
  | "starting"
  | "stopping";

export interface ComposePhase {
  stage: ComposeStage;
  /** One line naming the phase and how far along it is. */
  label: string;
  /** The same without the phase's name, for under a heading that already says it. */
  detail?: string;
  /** 0-100 for the bar. */
  percent: number;
  amount?: ProgressAmount;
}

/** A download bar stops short of full until every image is ready. */
const MAX_DOWNLOAD_PERCENT = 99;

interface DownloadAmount {
  downloaded: number;
  total: number;
  estimated: boolean;
}

/**
 * Bytes downloaded of the pull's size as the registries gave it before the
 * pull began. A layer already on this computer downloads nothing and counts
 * for neither; a finished one counts whole.
 */
function measureDownload(state: ComposeProgressState): DownloadAmount {
  let downloaded = 0;
  let total = 0;
  for (const [id, size] of state.expectedLayers) {
    const layer = state.layers.get(id);
    if (layer?.present) continue;
    total += size;
    downloaded += layer?.done ? size : Math.min(layer?.current ?? 0, size);
  }
  return { downloaded, total, estimated: false };
}

/**
 * Without the registries' sizes: Compose names a layer before it tells its
 * size, so a layer without one counts as the average of those that have one
 * and the total is marked estimated; it never shrinks once shown.
 */
function estimateDownload(state: ComposeProgressState): DownloadAmount {
  const layers = [...state.layers.values()].filter((l) => !l.present);
  const sized = layers.filter((l) => l.total > 0);
  const downloaded = sized.reduce((sum, l) => sum + l.current, 0);
  const unsized = layers.filter((l) => l.total === 0);
  const sizedTotal = sized.reduce((sum, l) => sum + l.total, 0);
  const average = sized.length > 0 ? sizedTotal / sized.length : 0;
  const total = Math.round(sizedTotal + unsized.length * average);
  state.downloadTotal = Math.max(state.downloadTotal, total);
  return {
    downloaded,
    total: state.downloadTotal,
    estimated: unsized.length > 0,
  };
}

/** "RabbitMQ", "server and web app", "RabbitMQ, MongoDB and 1 more", by plain names. */
function nameServices(services: readonly string[]): string {
  const named = services.slice(0, NAMED_WAITING).map(serviceName);
  const rest = services.length - named.length;
  return rest > 0
    ? `${named.join(", ")} and ${rest} more`
    : named.join(" and ");
}

/** "Stopping GAIA: waiting on RabbitMQ, MongoDB and 1 more (3 of 6 stopped)". */
function describeStop(stopping: Map<string, boolean>): ComposePhase {
  const waiting = [...stopping]
    .filter(([, done]) => !done)
    .map(([service]) => service);
  const stopped = stopping.size - waiting.length;
  const counted = `${stopped} of ${stopping.size} stopped`;
  const percent = Math.floor((stopped / stopping.size) * 100);
  if (waiting.length === 0) {
    return { stage: "stopping", label: `Stopping GAIA: ${counted}`, percent };
  }
  return {
    stage: "stopping",
    label: `Stopping GAIA: waiting on ${nameServices(waiting)} (${counted})`,
    percent,
  };
}

/**
 * "Starting GAIA: waiting for server to be ready (7 of 9 up)": what compose
 * is holding for, a health check first, else the services not yet up.
 */
function describeStart(state: ComposeProgressState): ComposePhase {
  const containers = [...state.containers];
  const up = containers.filter(([, isUp]) => isUp).length;
  const counted = `${up} of ${containers.length} up`;
  const percent = Math.floor((up / containers.length) * 100);
  const amount: ProgressAmount = {
    done: up,
    total: containers.length,
    unit: "services",
    estimated: false,
  };
  const notUp = containers.filter(([, isUp]) => !isUp).map(([s]) => s);
  const doing =
    state.awaitingHealth.size > 0
      ? `waiting for ${nameServices([...state.awaitingHealth])} to be ready`
      : notUp.length > 0
        ? `starting ${nameServices(notUp)}`
        : null;
  return {
    stage: "starting",
    label: doing
      ? `Starting GAIA: ${doing} (${counted})`
      : `Starting GAIA: ${up} of ${containers.length} services up`,
    detail: doing ?? `${up} of ${containers.length} services up`,
    percent,
    amount,
  };
}

/** Every image still being pulled has its layers, and all of them are downloaded: Docker is unpacking. */
function isUnpacking(state: ComposeProgressState): boolean {
  const layers = [...state.layers.values()];
  const pulling = [...state.images]
    .filter(([, imageState]) => imageState === "downloading")
    .map(([ref]) => ref);
  return pulling.every(
    (ref) =>
      layers.some((layer) => layer.image === ref) &&
      layers.every((layer) => layer.image !== ref || layer.done),
  );
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
      stage: "building",
      label: `Building GAIA from source: step ${stepsDone + 1} of ${steps.length}`,
      percent: Math.floor((stepsDone / steps.length) * 100),
    };
  }

  const images = [...state.images.values()];
  if (images.includes("building") && !images.includes("downloading")) {
    return {
      stage: "building",
      label: "Building GAIA from source: saving the images",
      percent: 99,
    };
  }
  if (images.includes("downloading")) {
    const ready = images.filter((image) => image === "ready").length;
    const download =
      state.expectedLayers.size > 0
        ? measureDownload(state)
        : estimateDownload(state);
    const amount: ProgressAmount = {
      done: download.downloaded,
      total: download.total,
      unit: "bytes",
      estimated: download.estimated,
    };
    // Full only once every image is ready: unpacking follows the last byte.
    const percent =
      amount.total > 0
        ? Math.min(
            MAX_DOWNLOAD_PERCENT,
            Math.floor((amount.done / amount.total) * 100),
          )
        : 0;
    const counted = `${ready} of ${images.length} ready`;
    if (isUnpacking(state)) {
      return {
        stage: "unpacking",
        label: `Unpacking GAIA's images: ${formatBytes(download.downloaded)} downloaded (${counted})`,
        detail: `Unpacking · ${ready} of ${images.length} images ready`,
        percent,
        amount,
      };
    }
    const size =
      amount.total > 0
        ? formatByteProgress(amount.done, amount.total, amount.estimated)
        : "starting";
    return {
      stage: "downloading",
      label: `Downloading GAIA's images: ${size} (${counted})`,
      detail: `${ready} of ${images.length} images ready`,
      percent,
      ...(amount.total > 0 ? { amount } : {}),
    };
  }

  return state.containers.size > 0 ? describeStart(state) : null;
}

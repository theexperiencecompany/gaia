/**
 * Fold `docker compose --progress json` events into the progress state: which
 * images are downloading or built, each layer's bytes, each build step, and
 * which containers are starting, up or stopping. compose-progress.ts reads it.
 * @module lib/compose-events
 */

import type {
  ComposeEvent,
  ComposeProgressState,
} from "./compose-progress.types.js";
import { serviceName } from "./display-names.js";

/**
 * A fresh state. expectedServices are listed, not up, from the start: compose
 * names a stopped container only once it reaches it, after its dependencies.
 */
export function createComposeProgress(
  expectedLayers: ReadonlyMap<string, number> = new Map(),
  expectedServices: readonly string[] = [],
): ComposeProgressState {
  return {
    images: new Map(),
    layers: new Map(),
    steps: new Map(),
    containers: new Map(expectedServices.map((service) => [service, false])),
    started: new Set(),
    starting: new Set(),
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
  // "Running": compose found it up already; "Healthy": a dependency check passed;
  // "Exited": a one-shot service a dependent waits on finished cleanly.
  const up = ["Started", "Running", "Healthy", "Exited"].includes(e.text ?? "");
  if (e.status === "Error") {
    state.errors.push(`${service}: ${e.details ?? e.text ?? "error"}`);
  }
  // "Waiting": compose holds what depends on this service until its health check passes.
  if (e.text === "Starting") state.starting.add(service);
  if (up) state.starting.delete(service);
  if (e.text === "Waiting") state.awaitingHealth.add(service);
  // "Exited": a one-shot dependency finished, so what waits on it may start.
  if (e.text === "Healthy" || e.text === "Exited") {
    state.awaitingHealth.delete(service);
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

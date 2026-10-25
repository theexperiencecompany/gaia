/**
 * The rows every command that (re)starts the self-host stack shows: getting
 * the images, starting each service, then waiting for GAIA to answer. `gaia
 * up`, `gaia start`, `gaia update`, `gaia restore` and `gaia bots` share
 * them, so a start reads the same wherever it happens.
 * @module lib/start-steps
 */

import type { CLIStore } from "../ui/store.js";
import { formatBytes } from "./byte-size.js";
import type { ComposePhase } from "./compose-progress.types.js";
import type { DownloadProgress } from "./download.js";
import { createEtaTracker } from "./eta.js";
import { type WaitForServicesResult, waitForUpReadiness } from "./readiness.js";
import {
  findStep,
  finishStep,
  type RunStep,
  skipStep,
  startStep,
  updateStep,
} from "./run-steps.js";
import type { RunSubstep } from "./run-steps.types.js";
import { type StartServicesOptions, startServices } from "./service-starter.js";

/** Shown under a source build: it is long, and stopping it is safe. */
const BUILD_HINT = "usually 10-20 minutes · safe to leave running";

/** The image step: downloaded, or for --build built; skipped when the images are already here. */
export function imagesStep(build: boolean) {
  return build
    ? { id: "download", label: "Building GAIA", doneLabel: "Built GAIA" }
    : {
        id: "download",
        label: "Downloading GAIA",
        doneLabel: "Downloaded GAIA",
      };
}

export const START_STEP = {
  id: "start",
  label: "Starting GAIA",
  doneLabel: "Started GAIA",
} as const;

/** The step a compose phase belongs to: getting the images, or starting them. */
function composeStepId(phase: ComposePhase): "download" | "start" {
  return phase.stage === "starting" || phase.stage === "stopping"
    ? "start"
    : "download";
}

function stepState(store: CLIStore, id: string): RunStep["state"] | undefined {
  return findStep(store, id)?.state;
}

/**
 * Close the download step once compose moves on: done if it got or built
 * anything, left out when the images were already here.
 */
function settleDownload(store: CLIStore): void {
  const step = findStep(store, "download");
  if (step?.state === "pending") skipStep(store, "download");
  if (step?.state !== "active") return;
  const worked =
    step.amount !== undefined ||
    step.substeps !== undefined ||
    step.percent !== undefined;
  if (worked) finishStep(store, "download");
  else skipStep(store, "download");
}

/** A step's bar and sub-line from a download's bytes, with the time left once it can tell. */
export function downloadReporter(
  store: CLIStore,
  id: string,
): (progress: DownloadProgress) => void {
  const eta = createEtaTracker();
  return ({ received, total }) =>
    updateStep(
      store,
      id,
      total === null
        ? { detail: `${formatBytes(received)} downloaded` }
        : {
            amount: {
              done: received,
              total,
              unit: "bytes",
              estimated: false,
            },
            etaMs: eta.update(received, total),
          },
    );
}

/** One step's line per service from compose's phases, for a stop. */
export function stopPhaseReporter(
  store: CLIStore,
  id: string,
): (phase: ComposePhase) => void {
  return (phase) =>
    updateStep(store, id, {
      detail: phase.parts ? undefined : phase.detail,
      substeps: phase.parts,
    });
}

/** Drive the download and start steps from compose's phases: a bar for bytes, a line per service. */
export function composePhaseReporter(
  store: CLIStore,
): (phase: ComposePhase) => void {
  const eta = createEtaTracker();
  return (phase) => {
    const id = composeStepId(phase);
    if (id === "start") settleDownload(store);
    if (stepState(store, id) !== "active") startStep(store, id);
    // A per-service line says more than a count of services would.
    const bytes = phase.amount?.unit === "bytes" ? phase.amount : undefined;
    updateStep(store, id, {
      detail: phase.parts ? undefined : (phase.detail ?? phase.label),
      substeps: phase.parts,
      percent: phase.percent,
      amount: bytes,
      etaMs: bytes ? eta.update(bytes.done, bytes.total) : undefined,
    });
  };
}

/**
 * One compose start whose phases drive the download and start steps; the
 * start step stays running for {@link waitForGaia}. Returns how many
 * services it started (0: everything was already running).
 * @throws ComposeError naming the cause, the next step and the log file.
 */
export async function startSelfhostServices(
  store: CLIStore,
  repoPath: string,
  portOverrides: Record<number, number>,
  options: StartServicesOptions,
): Promise<number> {
  startStep(
    store,
    "download",
    options.build
      ? { hint: BUILD_HINT }
      : { detail: "Checking which images this computer needs" },
  );
  const { startedServices } = await startServices(
    repoPath,
    "selfhost",
    undefined,
    portOverrides,
    composePhaseReporter(store),
    options,
  );
  settleDownload(store);
  return startedServices;
}

/**
 * Wait for GAIA to answer. "Started GAIA" means it does, so the start step
 * runs on through the wait and fails when GAIA never answers.
 */
export async function waitForGaia(
  store: CLIStore,
  endpoints: { apiUrl: string; webPort: number },
  startedServices: number,
): Promise<WaitForServicesResult> {
  if (stepState(store, "start") !== "active") startStep(store, "start");
  const services = (findStep(store, "start")?.substeps ?? []).map(
    (service): RunSubstep => ({ ...service, state: "done", note: undefined }),
  );
  const showWaiting = (pending: readonly string[]): void =>
    updateStep(store, "start", {
      substeps: [
        ...services,
        {
          id: "answer",
          label: "Waiting for GAIA to answer",
          state: "active",
          ...(pending.length > 0 ? { note: pending.join(" and ") } : {}),
        },
      ],
    });
  updateStep(store, "start", {
    detail: undefined,
    percent: undefined,
    amount: undefined,
    etaMs: undefined,
  });
  showWaiting([]);
  const readiness = await waitForUpReadiness(store, endpoints, showWaiting);
  if (readiness.ready) {
    finishStep(
      store,
      "start",
      startedServices === 0 ? "GAIA was already running" : undefined,
    );
  } else {
    updateStep(store, "start", { state: "failed", endedAt: Date.now() });
  }
  return readiness;
}

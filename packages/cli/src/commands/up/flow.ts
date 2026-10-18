/**
 * `gaia up` — one-command self-hosted setup.
 *
 * Flow: make Docker available (one install offer) → check the release's
 * images exist for this computer → resolve the install (recorded, or this
 * release's setup files downloaded; a source clone only for --build) →
 * env-setup selfhost pipeline with pre-sourced answers (flags → saved config →
 * defaults) → download the images → start → wait for GAIA to answer → save a
 * flagged AI provider → the summary card. Each phase is one step on screen.
 * @module commands/up/flow
 */

import { execFile } from "node:child_process";
import * as os from "node:os";
import type { SetupStatusResponse } from "@gaia/shared/api/generated";
import {
  createUpAnswerResolver,
  DEFAULT_INSTALL_DIR,
  portOverridesFromFlags,
  resolveRecordedInstall,
  type UpFlags,
} from "../../lib/answers.js";
import { formatBytes } from "../../lib/byte-size.js";
import { explainImageGap } from "../../lib/compose-failure.js";
import type { ComposePhase } from "../../lib/compose-progress.js";
import { readConfig, updateConfig } from "../../lib/config.js";
import {
  joinedDockerGroupThisRun,
  resumedSteps,
} from "../../lib/docker-group.js";
import type { DownloadProgress } from "../../lib/download.js";
import {
  DEFAULT_WEB_PORT,
  localApiUrl,
  primaryWebUrl,
  reachableWebUrls,
} from "../../lib/endpoints.js";
import { runEnvSetup } from "../../lib/env-setup.js";
import { readPinnedGaiaVersion } from "../../lib/env-writer.js";
import { createEtaTracker } from "../../lib/eta.js";
import { runPortChecks } from "../../lib/flow-utils.js";
import { findReleaseImageGap } from "../../lib/image-availability.js";
import {
  LLM_PROVIDER_NAMES,
  saveLlmProvider,
  validateLlmFlags,
} from "../../lib/llm-flags.js";
import { homeRelative } from "../../lib/paths.js";
import {
  ensurePrerequisites,
  joinNames,
  PrerequisiteDeclined,
} from "../../lib/prerequisite-install.js";
import { waitForUpReadiness } from "../../lib/readiness.js";
import {
  cloneRelease,
  GAIA_REPO_URL,
  pinReleaseImages,
} from "../../lib/release.js";
import {
  endActiveStep,
  finishStep,
  initSteps,
  type RunStep,
  STEPS_KEY,
  skipStep,
  startStep,
  updateStep,
} from "../../lib/run-steps.js";
import { placeBundle, stageBundle } from "../../lib/selfhost-bundle.js";
import {
  assertBuildableInstall,
  detectSetupMode,
  isGaiaInstall,
  startServices,
} from "../../lib/service-starter.js";
import { readSetupEndpoint } from "../../lib/setup-endpoints.js";
import { CLI_VERSION, GAIA_RELEASE_IMAGE_TAG } from "../../lib/version.js";
import type { CLIStore } from "../../ui/store.js";
import type { UpOutcome } from "./summary.js";

/** The command a missing-image error points `gaia up` users to. */
const UP_REBUILD_COMMAND = "gaia up --build";

/** Shown under a source build: it is long, and stopping it is safe. */
const BUILD_HINT = "usually 10-20 minutes · safe to leave running";

/** Store key for the one line a run that stopped on the user's answer ends with. */
export const UP_NOTICE_KEY = "upNotice";

/** How an install comes to be: there already, this release's setup files, or (for --build) its source. */
type InstallSource = "existing" | "bundle" | "clone";

/** The steps `gaia up` shows, in order; download, start and wait drop out with --no-start. */
function upSteps(options: UpFlags, source: InstallSource) {
  const provider = options.llmProvider
    ? LLM_PROVIDER_NAMES[options.llmProvider]
    : null;
  const files = {
    existing: {
      label: "Finding your install",
      doneLabel: "Using your install",
      minor: true,
    },
    bundle: {
      label: "Getting GAIA's setup files",
      doneLabel: "Got GAIA's setup files",
      minor: true,
    },
    clone: {
      label: "Downloading GAIA's source",
      doneLabel: "Downloaded GAIA's source",
    },
  }[source];
  return [
    {
      id: "docker",
      label: "Checking Docker",
      doneLabel: "Docker is ready",
      minor: true,
    },
    { id: "files", ...files },
    {
      id: "configure",
      label: "Saving your settings",
      doneLabel: "Saved your settings",
      minor: true,
    },
    ...(options.noStart
      ? []
      : [
          options.build
            ? {
                id: "download",
                label: "Building GAIA",
                doneLabel: "Built GAIA",
              }
            : {
                id: "download",
                label: "Downloading GAIA",
                doneLabel: "Downloaded GAIA",
              },
          { id: "start", label: "Starting GAIA", doneLabel: "Started GAIA" },
          { id: "wait", label: "Almost ready", doneLabel: "GAIA is ready" },
        ]),
    ...(provider
      ? [
          {
            id: "provider",
            label: `Checking your ${provider} key`,
            doneLabel: `Saved your ${provider} key`,
          },
        ]
      : []),
  ];
}

/**
 * Where the install comes from: there already, this release's setup files,
 * or for --build its source.
 * @throws Error when --build meets an install of setup files, which has no source to build.
 */
function installSource(targetPath: string, build: boolean): InstallSource {
  if (!isGaiaInstall(targetPath)) return build ? "clone" : "bundle";
  if (build) assertBuildableInstall(targetPath);
  return "existing";
}

function developerTreeError(targetPath: string): Error {
  return new Error(
    `${targetPath} is set up for development (apps/api/.env is in developer mode), and 'gaia up' would overwrite its settings.\n` +
      "Run it with --force-dev-tree to go ahead anyway.",
  );
}

/** Record a failure: the running row turns red and the error is shown under the list. */
function fail(store: CLIStore, error: Error): void {
  endActiveStep(store, "failed");
  store.setError(error);
}

export async function runUpFlow(
  store: CLIStore,
  options: UpFlags = {},
): Promise<void> {
  // Fail loud on contradictory flags before any side effect — every message
  // names the flag that fixes it.
  validateLlmFlags(options);
  // A docker-group relaunch continues the first process's run, and its clock.
  const runStartedAt = Math.min(
    Date.now(),
    ...Object.values(resumedSteps()).map((step) => step.startedAt),
  );

  const recordedInstall = resolveRecordedInstall();
  const targetPath = recordedInstall ?? DEFAULT_INSTALL_DIR;
  let source: InstallSource;
  try {
    source = installSource(targetPath, options.build === true);
  } catch (e) {
    store.setError(e as Error);
    return;
  }

  // Seed the values layer BEFORE any waitForInput can block: every prompt the
  // pipeline raises resolves from flags → saved config → defaults.
  store.pushAnswerResolver(createUpAnswerResolver({ repoPath: targetPath }));
  initSteps(store, upSteps(options, source));

  // 1. Docker, the release's images, and ports.
  store.setStep("Prerequisites");
  if (!(await prepareDocker(store, options, source))) return;
  if (
    !options.build &&
    !(await checkReleaseImages(store, targetPath, source !== "existing"))
  ) {
    return;
  }
  const portOverrides = await runPortChecks(store, "selfhost");
  if (portOverrides === null) {
    endActiveStep(store, "failed");
    return;
  }
  Object.assign(portOverrides, portOverridesFromFlags(options));

  // Never rewrite a developer-mode checkout's .env; an unconfigured or
  // self-host one (a half-finished first run) is safe to resume.
  if (
    source === "existing" &&
    targetPath !== recordedInstall &&
    !options.forceDevTree &&
    (await detectSetupMode(targetPath)) === "developer"
  ) {
    fail(store, developerTreeError(targetPath));
    return;
  }
  finishStep(store, "docker");

  // 2. The install: the recorded/existing one, else this release's setup files.
  store.setStep("Repository Setup");
  startStep(store, "files");
  if (!(await prepareInstall(store, targetPath, source))) return;
  // Record the install before anything else can fail, so a rerun resumes
  // this checkout instead of tripping over it. The sandbox choice is saved
  // here too: every compose start reads it from the config.
  updateConfig(
    options.codeSandbox === undefined
      ? { repoPath: targetPath }
      : { repoPath: targetPath, codeSandbox: options.codeSandbox },
  );
  finishStep(
    store,
    "files",
    source === "existing"
      ? `Using your install at ${homeRelative(targetPath)}`
      : undefined,
  );

  // 3. Settings — selfhost pipeline with pre-sourced answers.
  store.setStep("Environment Setup");
  startStep(store, "configure");
  await runEnvSetup(store, targetPath, "selfhost", portOverrides, {
    llmProvider: options.llmProvider,
    domain: options.domain,
  });
  if (store.currentState.error) {
    endActiveStep(store, "failed");
    return;
  }
  finishStep(store, "configure");

  const webPort = portOverrides[DEFAULT_WEB_PORT] ?? DEFAULT_WEB_PORT;
  const outcome: UpOutcome = {
    webUrl: primaryWebUrl(webPort, options.domain),
    reachableUrls: reachableWebUrls(webPort, options.domain),
    noStart: options.noStart === true,
    stillStarting: false,
    setupComplete: false,
    codeSandbox: readConfig()?.codeSandbox === true,
    joinedDockerGroup: joinedDockerGroupThisRun(),
    elapsedMs: 0,
    startedServices: 0,
  };
  if (options.noStart) {
    finishUp(store, targetPath, {
      ...outcome,
      elapsedMs: Date.now() - runStartedAt,
    });
    return;
  }

  // 4. Start, then wait for GAIA to answer (a timeout still exits 0).
  store.setStep("Project Setup");
  try {
    outcome.startedServices = await startSelfhostServices(
      store,
      targetPath,
      portOverrides,
      options,
    );
  } catch (e) {
    fail(store, e as Error);
    return;
  }
  startStep(store, "wait");
  const apiUrl = localApiUrl("selfhost", portOverrides);
  const readiness = await waitForUpReadiness(store, { apiUrl, webPort });
  if (readiness.ready) finishStep(store, "wait");
  else updateStep(store, "wait", { state: "failed", endedAt: Date.now() });
  outcome.stillStarting = !readiness.ready;
  outcome.setupComplete = readiness.ready && (await isSetupComplete(apiUrl));

  // 5. The flagged AI provider, checked by the API's live probe before saving.
  const providerError = await saveFlaggedProvider(
    store,
    targetPath,
    options,
    readiness.ready,
  );
  if (options.llmProvider) {
    if (providerError) outcome.unsavedProvider = options.llmProvider;
    else outcome.savedProvider = options.llmProvider;
  }
  finishUp(store, targetPath, {
    ...outcome,
    elapsedMs: Date.now() - runStartedAt,
  });
  if (providerError) {
    store.setError(providerError);
    return;
  }
  if (readiness.ready) openSetupWizard(outcome.webUrl, options);
}

/**
 * Make Docker available, installing it with consent. Returns false when the
 * run stops here: a failure, a declined install (one line saying so), or a
 * relaunch into the docker group.
 */
async function prepareDocker(
  store: CLIStore,
  options: UpFlags,
  source: InstallSource,
): Promise<boolean> {
  startStep(store, "docker");
  try {
    const readiness = await ensurePrerequisites(store, {
      needGit: source === "clone",
      assumeYes: options.yes === true,
      // The clock restarts here: time spent reading the question is not install time.
      onInstallStart: (missing) =>
        startStep(store, "docker", {
          label: `Installing ${joinNames(missing)}`,
          doneLabel: `${joinNames(missing)} installed`,
          minor: false,
          startedAt: Date.now(),
        }),
      onInstallProgress: (progress) =>
        updateStep(store, "docker", {
          label: progress.label,
          detail: progress.detail,
          amount: progress.amount,
        }),
    });
    return readiness !== "relaunch";
  } catch (e) {
    if (!(e instanceof PrerequisiteDeclined)) {
      fail(store, e as Error);
      return false;
    }
    skipStep(store, "docker");
    store.updateData(UP_NOTICE_KEY, e.message);
    process.exitCode = 1;
    return false;
  }
}

/**
 * Fail in seconds, not after a clone, when the release cannot run on this
 * computer. Returns false after recording the error.
 */
async function checkReleaseImages(
  store: CLIStore,
  targetPath: string,
  needsClone: boolean,
): Promise<boolean> {
  const tag = needsClone
    ? GAIA_RELEASE_IMAGE_TAG
    : readPinnedGaiaVersion(targetPath);
  store.setStatus(`Checking that GAIA ${tag} is available for this computer…`);
  const gap = await findReleaseImageGap(tag, readConfig()?.bots ?? []);
  if (!gap) return true;
  const { cause, next } = explainImageGap(gap, UP_REBUILD_COMMAND);
  fail(store, new Error(`${cause}\n${next}`));
  return false;
}

/** A step's bar and sub-line from a download's bytes, with the time left once it can tell. */
function downloadReporter(
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

/**
 * Lay this CLI's release into a fresh install: its setup files, or for
 * --build a clone of its source. Returns false after recording the error.
 */
async function prepareInstall(
  store: CLIStore,
  targetPath: string,
  source: InstallSource,
): Promise<boolean> {
  if (source === "existing") return true;
  try {
    if (source === "bundle") {
      const staged = await stageBundle(
        targetPath,
        GAIA_RELEASE_IMAGE_TAG,
        downloadReporter(store, "files"),
      );
      await placeBundle(staged.manifest, staged.stagingDir, targetPath, []);
      pinReleaseImages(targetPath, GAIA_RELEASE_IMAGE_TAG);
      return true;
    }
    updateStep(store, "files", { detail: "Connecting to GitHub…" });
    await cloneRelease(targetPath, GAIA_REPO_URL, (percent, phase) => {
      updateStep(
        store,
        "files",
        phase ? { percent, detail: phase } : { percent },
      );
    });
  } catch (e) {
    fail(
      store,
      new Error(
        `Couldn't get GAIA into ${homeRelative(targetPath)}: ${(e as Error).message}`,
      ),
    );
    return false;
  }
  return true;
}

/**
 * Auto-open the setup wizard when running interactively on macOS. Non-blocking,
 * errors are ignored: the URL is already printed on the success screen and in
 * the plain summary.
 */
function openSetupWizard(webUrl: string, options: UpFlags): void {
  const isTTY = process.stdin.isTTY === true && process.stdout.isTTY === true;
  if (!options.yes && isTTY && os.platform() === "darwin") {
    execFile("open", [`${webUrl}/setup`], () => undefined);
  }
}

/**
 * Save the `--llm-provider` the run was given into the now-running instance.
 * Returns the error to show when it was not saved, else null.
 */
async function saveFlaggedProvider(
  store: CLIStore,
  repoPath: string,
  options: UpFlags,
  ready: boolean,
): Promise<Error | null> {
  const { llmProvider } = options;
  if (!llmProvider) return null;
  const name = LLM_PROVIDER_NAMES[llmProvider];
  startStep(store, "provider");
  if (!ready) {
    endActiveStep(store, "failed");
    return new Error(
      `GAIA didn't answer in time, so your ${name} key wasn't saved.\n` +
        "Once 'gaia status' shows it running, run 'gaia up' again with the same flags.",
    );
  }
  try {
    await saveLlmProvider(repoPath, { ...options, llmProvider });
  } catch (e) {
    endActiveStep(store, "failed");
    return new Error(
      `Your ${name} key wasn't saved: ${(e as Error).message}\n` +
        `Check the key and run 'gaia up --llm-provider ${llmProvider} --llm-key <key>' again, or add it on the setup page above.`,
    );
  }
  finishStep(store, "provider");
  return null;
}

/** The step a compose phase belongs to: getting the images, or starting them. */
function composeStepId(phase: ComposePhase): "download" | "start" {
  return phase.stage === "starting" || phase.stage === "stopping"
    ? "start"
    : "download";
}

function stepState(store: CLIStore, id: string): RunStep["state"] | undefined {
  const steps = (store.currentState.data[STEPS_KEY] ?? []) as RunStep[];
  return steps.find((step) => step.id === id)?.state;
}

/** Close the download step once compose moves on: done if it ran, left out if the images were here. */
function settleDownload(store: CLIStore): void {
  const state = stepState(store, "download");
  if (state === "active") finishStep(store, "download");
  if (state === "pending") skipStep(store, "download");
}

/**
 * Compose start from the published images, or from a local build with --build:
 * one compose run whose phases drive two steps, the download and the start.
 * A failed start never turns into a build behind the user's back: building is
 * slow and CPU-heavy, and it would hide why the images did not come up.
 *
 * @throws ComposeError naming the cause, the next step and the log file.
 */
async function startSelfhostServices(
  store: CLIStore,
  repoPath: string,
  portOverrides: Record<number, number>,
  options: UpFlags,
): Promise<number> {
  startStep(
    store,
    "download",
    options.build
      ? { hint: BUILD_HINT }
      : { detail: "Checking which images this computer needs" },
  );
  const eta = createEtaTracker();
  const onPhase = (phase: ComposePhase): void => {
    const id = composeStepId(phase);
    if (id === "start") settleDownload(store);
    if (stepState(store, id) !== "active") startStep(store, id);
    const bytes = phase.amount?.unit === "bytes" ? phase.amount : undefined;
    updateStep(store, id, {
      detail: phase.detail ?? phase.label,
      percent: phase.percent,
      amount: phase.amount,
      etaMs: bytes ? eta.update(bytes.done, bytes.total) : undefined,
    });
  };
  const { startedServices } = await startServices(
    repoPath,
    "selfhost",
    undefined,
    portOverrides,
    onPhase,
    // A rerun keeps the images it has; `gaia update` refreshes them.
    {
      ...(options.build ? { build: true } : { pull: "missing" as const }),
      rebuildCommand: UP_REBUILD_COMMAND,
      onLogFile: (logPath) => store.updateData("logPath", logPath),
    },
  );
  settleDownload(store);
  if (stepState(store, "start") !== "active") startStep(store, "start");
  finishStep(
    store,
    "start",
    startedServices === 0 ? "GAIA was already running" : undefined,
  );
  return startedServices;
}

/**
 * Whether the browser wizard has nothing left to do (an admin and a working
 * AI provider exist). An unreadable status counts as not complete, so the
 * summary keeps pointing at the wizard.
 */
async function isSetupComplete(apiUrl: string): Promise<boolean> {
  const status = await readSetupEndpoint<SetupStatusResponse>(apiUrl, "status");
  return "data" in status && !status.data.needs_setup;
}

/** Record the install and hand the outcome to the summary card. */
function finishUp(store: CLIStore, repoPath: string, outcome: UpOutcome): void {
  // A partial update: the saved sandbox choice must survive a finished run.
  updateConfig({
    version: CLI_VERSION,
    setupComplete: true,
    setupMethod:
      (store.currentState.data.envMethod as "manual" | "infisical") || "manual",
    repoPath,
  });
  store.updateData("setupMode", "selfhost");
  store.updateData("upOutcome", outcome);
  store.updateData("finished", true);
  store.setStep("Finished");
}

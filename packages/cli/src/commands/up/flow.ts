/**
 * `gaia up` — one-command self-hosted setup.
 *
 * Flow: ensure prerequisites (Git and Docker, one install offer) → check the
 * release's images exist for this computer → resolve the install (recorded or
 * fresh clone) → env-setup selfhost pipeline with pre-sourced answers (flags →
 * saved config → defaults) → compose start → wait for GAIA to answer → save a
 * flagged AI provider → the summary card. Each phase is one row of the step list.
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
import { explainImageGap } from "../../lib/compose-failure.js";
import type { ComposeStage } from "../../lib/compose-progress.js";
import { readConfig, updateConfig } from "../../lib/config.js";
import {
  joinedDockerGroupThisRun,
  resumedStepStarts,
} from "../../lib/docker-group.js";
import {
  DEFAULT_WEB_PORT,
  localApiUrl,
  primaryWebUrl,
  reachableWebUrls,
} from "../../lib/endpoints.js";
import { runEnvSetup } from "../../lib/env-setup.js";
import { readPinnedGaiaVersion } from "../../lib/env-writer.js";
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
} from "../../lib/prerequisite-install.js";
import { waitForUpReadiness } from "../../lib/readiness.js";
import { cloneRelease, GAIA_REPO_URL } from "../../lib/release.js";
import {
  endActiveStep,
  finishStep,
  initSteps,
  startStep,
  updateStep,
} from "../../lib/run-steps.js";
import {
  detectSetupMode,
  isGaiaCheckout,
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

/** The start row's label for what compose is doing: the download is most of a first run. */
const START_STAGE_LABELS: Record<ComposeStage, string> = {
  building: "Building GAIA",
  downloading: "Downloading GAIA's images",
  unpacking: "Unpacking GAIA's images",
  starting: "Starting GAIA",
  stopping: "Stopping GAIA",
};

/** The rows `gaia up` shows, in order; start and wait drop out with --no-start. */
function upSteps(options: UpFlags, needsClone: boolean) {
  const provider = options.llmProvider
    ? LLM_PROVIDER_NAMES[options.llmProvider]
    : null;
  return [
    {
      id: "check",
      label: "Checking Git and Docker",
      doneLabel: "Git and Docker are ready",
    },
    needsClone
      ? {
          id: "download",
          label: "Downloading GAIA",
          doneLabel: "Downloaded GAIA",
        }
      : {
          id: "download",
          label: "Finding your install",
          doneLabel: "Using your install",
        },
    {
      id: "configure",
      label: "Configuring GAIA",
      doneLabel: "Configured GAIA",
    },
    ...(options.noStart
      ? []
      : [
          options.build
            ? {
                id: "start",
                label: "Building GAIA",
                doneLabel: "Built and started GAIA",
              }
            : {
                id: "start",
                label: "Starting GAIA",
                doneLabel: "Started GAIA",
              },
          {
            id: "wait",
            label: "Waiting for GAIA to answer",
            doneLabel: "GAIA is answering",
          },
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
    ...Object.values(resumedStepStarts()),
  );

  const recordedInstall = resolveRecordedInstall();
  const targetPath = recordedInstall ?? DEFAULT_INSTALL_DIR;
  const needsClone = !isGaiaCheckout(targetPath);

  // Seed the values layer BEFORE any waitForInput can block: every prompt the
  // pipeline raises resolves from flags → saved config → defaults.
  store.pushAnswerResolver(createUpAnswerResolver({ repoPath: targetPath }));
  initSteps(store, upSteps(options, needsClone));

  // 1. Prerequisites, the release's images, and ports.
  store.setStep("Prerequisites");
  startStep(store, "check");
  try {
    const readiness = await ensurePrerequisites(store, {
      needGit: needsClone,
      assumeYes: options.yes === true,
      // The clock restarts here: time spent reading the question is not install time.
      onInstallStart: (missing) =>
        startStep(store, "check", {
          label: `Installing ${joinNames(missing)}`,
          doneLabel: `Installed ${joinNames(missing)}`,
          startedAt: Date.now(),
        }),
    });
    if (readiness === "relaunch") return;
  } catch (e) {
    fail(store, e as Error);
    return;
  }
  if (
    !options.build &&
    !(await checkReleaseImages(store, targetPath, needsClone))
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
    !needsClone &&
    targetPath !== recordedInstall &&
    !options.forceDevTree &&
    (await detectSetupMode(targetPath)) === "developer"
  ) {
    fail(
      store,
      new Error(
        `${targetPath} is set up for development (apps/api/.env is in developer mode), and 'gaia up' would overwrite its settings.\n` +
          "Run it with --force-dev-tree to go ahead anyway.",
      ),
    );
    return;
  }
  finishStep(store, "check");

  // 2. The install: the recorded/existing one, or a fresh clone of this CLI's release.
  store.setStep("Repository Setup");
  startStep(store, "download");
  if (!(await prepareInstall(store, targetPath, needsClone))) return;
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
    "download",
    needsClone
      ? undefined
      : `Using your install at ${homeRelative(targetPath)}`,
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

/** Clone this CLI's release when there is no install yet. Returns false after recording the error. */
async function prepareInstall(
  store: CLIStore,
  targetPath: string,
  needsClone: boolean,
): Promise<boolean> {
  if (!needsClone) return true;
  updateStep(store, "download", {
    detail: "Connecting to GitHub…",
    percent: 0,
  });
  try {
    await cloneRelease(targetPath, GAIA_REPO_URL, (percent, phase) => {
      updateStep(
        store,
        "download",
        phase ? { percent, detail: phase } : { percent },
      );
    });
  } catch (e) {
    fail(
      store,
      new Error(
        `Couldn't download GAIA into ${targetPath}: ${(e as Error).message}`,
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

/**
 * Compose start from the published images, or from a local build with --build.
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
  startStep(store, "start", options.build ? { hint: BUILD_HINT } : {});
  const { startedServices } = await startServices(
    repoPath,
    "selfhost",
    (status) => updateStep(store, "start", { detail: status }),
    portOverrides,
    (phase) =>
      updateStep(store, "start", {
        label: START_STAGE_LABELS[phase.stage],
        detail: phase.label,
        percent: phase.percent,
      }),
    // A rerun keeps the images it has; `gaia update` refreshes them.
    {
      ...(options.build ? { build: true } : { pull: "missing" as const }),
      rebuildCommand: UP_REBUILD_COMMAND,
      onLogFile: (logPath) => store.updateData("logPath", logPath),
    },
  );
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

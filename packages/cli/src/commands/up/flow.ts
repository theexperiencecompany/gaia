/**
 * `gaia up` — one-command self-hosted setup.
 *
 * Flow: ensure prerequisites (Docker incl. install offer) → resolve target
 * repo (recorded install or fresh clone) → env-setup selfhost pipeline with
 * pre-sourced answers (flags → saved config → defaults) → compose pull-first
 * start → print the URL + browser wizard pointer.
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
import { readConfig, updateConfig } from "../../lib/config.js";
import { joinedDockerGroupThisRun } from "../../lib/docker-group.js";
import {
  DEFAULT_WEB_PORT,
  localApiUrl,
  primaryWebUrl,
  reachableWebUrls,
} from "../../lib/endpoints.js";
import { runEnvSetup } from "../../lib/env-setup.js";
import { readPinnedGaiaVersion } from "../../lib/env-writer.js";
import {
  delay,
  dependencyStepProgress,
  runPortChecks,
} from "../../lib/flow-utils.js";
import { findReleaseImageGap } from "../../lib/image-availability.js";
import { saveLlmProvider, validateLlmFlags } from "../../lib/llm-flags.js";
import { checkGit, ensureDocker, ensureGit } from "../../lib/prerequisites.js";
import { waitForUpReadiness } from "../../lib/readiness.js";
import { cloneRelease, GAIA_REPO_URL } from "../../lib/release.js";
import {
  detectSetupMode,
  isGaiaCheckout,
  startServices,
} from "../../lib/service-starter.js";
import { readSetupEndpoint } from "../../lib/setup-endpoints.js";
import { CLI_VERSION, GAIA_RELEASE_IMAGE_TAG } from "../../lib/version.js";
import type { CLIStore } from "../../ui/store.js";

export async function runUpFlow(
  store: CLIStore,
  options: UpFlags = {},
): Promise<void> {
  // Fail loud on contradictory flags before any side effect — every message
  // names the flag that fixes it.
  validateLlmFlags(options);

  const recordedInstall = resolveRecordedInstall();
  const targetPath = recordedInstall ?? DEFAULT_INSTALL_DIR;

  // Seed the values layer BEFORE any waitForInput can block: every prompt the
  // pipeline raises resolves from flags → saved config → defaults.
  store.pushAnswerResolver(createUpAnswerResolver({ repoPath: targetPath }));

  // 1. Prerequisites — git (needed when cloning) and Docker, each with an
  //    install offer on apt-based Linux.
  store.setStep("Prerequisites");
  store.setStatus("Checking system requirements...");

  const needsClone = !isGaiaCheckout(targetPath);
  const consent = { assumeYes: options.yes === true };
  try {
    if (needsClone) {
      await ensureGit(store, consent);
    } else {
      // An existing install needs no clone: git is reported, not required.
      const gitStatus = await checkGit();
      store.updateData("checks", {
        git: gitStatus === "success" ? gitStatus : "missing",
      });
    }
    if ((await ensureDocker(store, consent)) === "relaunch") {
      return;
    }
  } catch (e) {
    store.setError(e as Error);
    return;
  }

  // 1b. Images — fail in seconds, not after a clone, when the release cannot
  //     run on this computer.
  if (!options.build) {
    const tag = needsClone
      ? GAIA_RELEASE_IMAGE_TAG
      : readPinnedGaiaVersion(targetPath);
    store.setStatus(
      `Checking that GAIA ${tag} is available for this computer...`,
    );
    const gap = await findReleaseImageGap(tag, readConfig()?.bots ?? []);
    if (gap) {
      const { cause, next } = explainImageGap(gap, UP_REBUILD_COMMAND);
      store.setError(new Error(`${cause}\n${next}`));
      return;
    }
  }

  // 2. Ports — conflict-derived alternatives, then explicit flag overrides
  //    win (user intent beats automatic fallback).
  const portOverrides = await runPortChecks(store, "selfhost");
  if (portOverrides === null) {
    return;
  }
  Object.assign(portOverrides, portOverridesFromFlags(options));

  // 3. Never rewrite a developer-mode checkout's .env; an unconfigured or
  //    self-host one (a half-finished first run) is safe to resume.
  if (
    !needsClone &&
    targetPath !== recordedInstall &&
    !options.forceDevTree &&
    (await detectSetupMode(targetPath)) === "developer"
  ) {
    store.setError(
      new Error(
        `${targetPath} is configured as a developer checkout (apps/api/.env is in developer mode).\n` +
          "'gaia up' would overwrite its environment files.\n" +
          "Re-run with --force-dev-tree to proceed anyway.",
      ),
    );
    return;
  }

  // 4. Repository — reuse the recorded/existing install or clone fresh.
  store.setStep("Repository Setup");
  if (!needsClone) {
    store.setStatus(`Using your install at ${targetPath}`);
    await delay(500);
  } else {
    store.setStatus(`Downloading GAIA into ${targetPath}`);
    store.updateData("repoProgress", 0);
    store.updateData("repoPhase", "Connecting to GitHub...");
    try {
      await cloneRelease(targetPath, GAIA_REPO_URL, (progress, phase) => {
        store.updateData("repoProgress", progress);
        if (phase) store.updateData("repoPhase", phase);
      });
    } catch (e) {
      store.setError(
        new Error(
          `Couldn't download GAIA into ${targetPath}: ${(e as Error).message}`,
        ),
      );
      return;
    }
  }
  // Record the install before anything else can fail, so a rerun resumes
  // this checkout instead of tripping over it. The sandbox choice is saved
  // here too: every compose start reads it from the config.
  updateConfig(
    options.codeSandbox === undefined
      ? { repoPath: targetPath }
      : { repoPath: targetPath, codeSandbox: options.codeSandbox },
  );

  // 5. Environment — selfhost pipeline with pre-sourced answers; prompts
  //    never block because the answer resolver covers them.
  await runEnvSetup(store, targetPath, "selfhost", portOverrides, {
    llmProvider: options.llmProvider,
    domain: options.domain,
  });
  if (store.currentState.error) {
    return;
  }

  const webPort = portOverrides[DEFAULT_WEB_PORT] ?? DEFAULT_WEB_PORT;
  const webUrl = primaryWebUrl(webPort, options.domain);
  const reachableUrls = reachableWebUrls(webPort, options.domain);

  // 6. Start — pull-first fast path, local build fallback.
  if (options.noStart) {
    store.setStep("Finished");
    store.setStatus(
      "Environment configured. Start services later with 'gaia start'.",
    );
    finishUp(store, targetPath, webUrl, reachableUrls, { noStart: true });
    return;
  }

  try {
    await startSelfhostServices(store, targetPath, portOverrides, options);
  } catch (e) {
    store.setError(e as Error);
    return;
  }

  // Compose returning is not the stack answering. Probe localhost: the proxy
  // answers there even before a GAIA_DOMAIN resolves. A timeout exits 0.
  const apiUrl = localApiUrl("selfhost", portOverrides);
  const readiness = await waitForUpReadiness(store, { apiUrl, webPort });

  if (
    !(await saveFlaggedProvider(store, targetPath, options, readiness.ready))
  ) {
    return;
  }

  finishUp(store, targetPath, webUrl, reachableUrls, {
    noStart: false,
    savedProvider: options.llmProvider,
    stillStarting: !readiness.ready,
    setupComplete: readiness.ready && (await isSetupComplete(apiUrl)),
  });

  if (readiness.ready) openSetupWizard(webUrl, options);
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
 * Returns false after recording the error when it could not be saved.
 */
async function saveFlaggedProvider(
  store: CLIStore,
  repoPath: string,
  options: UpFlags,
  ready: boolean,
): Promise<boolean> {
  const { llmProvider } = options;
  if (!llmProvider) return true;
  if (!ready) {
    store.setError(
      new Error(
        `GAIA did not answer in time, so --llm-provider ${llmProvider} was not saved. Once 'gaia status' shows it healthy, run 'gaia up' again with the same flags.`,
      ),
    );
    return false;
  }
  store.setStatus("Saving the AI provider...");
  try {
    await saveLlmProvider(repoPath, { ...options, llmProvider });
  } catch (e) {
    store.setError(
      new Error(
        `Could not save --llm-provider ${llmProvider}: ${(e as Error).message}`,
      ),
    );
    return false;
  }
  return true;
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
): Promise<void> {
  store.setStep("Project Setup");
  store.updateData(
    "dependencyPhase",
    options.build ? "Building GAIA from source" : "Getting GAIA's images",
  );
  store.updateData("dependencyProgress", 0);
  store.updateData("dependencyLogs", []);
  store.updateData("dependencyComplete", false);
  store.setStatus(RESUME_HINT);

  await startServices(
    repoPath,
    "selfhost",
    () => store.setStatus(RESUME_HINT),
    portOverrides,
    dependencyStepProgress(store),
    // A rerun keeps the images it has; `gaia update` refreshes them.
    options.build
      ? { build: true, rebuildCommand: UP_REBUILD_COMMAND }
      : { pull: "missing", rebuildCommand: UP_REBUILD_COMMAND },
  );
  store.updateData("dependencyPhase", "GAIA's services are running");
  store.updateData("dependencyProgress", 100);
  store.updateData("dependencyComplete", true);
}

/** What `gaia up` says while Docker works: stopping is safe, a rerun resumes. */
const RESUME_HINT =
  "Ctrl+C stops here; run 'gaia up' again to pick up where it left off.";

/** The command a missing-image error points `gaia up` users to. */
const UP_REBUILD_COMMAND = "gaia up --build";

/**
 * Whether the browser wizard has nothing left to do (an admin and a working
 * AI provider exist). An unreadable status counts as not complete, so the
 * summary keeps pointing at the wizard.
 */
async function isSetupComplete(apiUrl: string): Promise<boolean> {
  const status = await readSetupEndpoint<SetupStatusResponse>(apiUrl, "status");
  return "data" in status && !status.data.needs_setup;
}

/** What a finished `gaia up` reached: configured only, started but not answering, or running. */
export function upHeadline(outcome: {
  noStart: boolean;
  stillStarting: boolean;
}): string {
  if (outcome.noStart) return "GAIA is configured. Nothing was started.";
  if (outcome.stillStarting) return "GAIA is still starting...";
  return "GAIA is ready!";
}

/** One line on the finished screen naming the AI provider `--llm-provider` saved. */
export function savedProviderSummary(provider: string): string {
  return `AI provider: ${provider} saved (change it any time in Settings → Providers & Tools)`;
}

/** One line on the finished screen saying how agent code runs on this instance. */
export function codeSandboxSummary(enabled: boolean): string {
  return enabled
    ? "Code execution: local sandbox (the host Docker socket is mounted into the API and worker)"
    : "Code execution: off until you save an E2B key, or rerun with --code-sandbox";
}

/** What the finished screen says when this run added the user to the docker group. */
export const DOCKER_GROUP_NOTE =
  "Your user was added to the 'docker' group. Other terminals get it after you log out and back in (or run 'newgrp docker'); until then, 'gaia status' there can't reach Docker.";

/** Record the install and move to the Finished step. */
function finishUp(
  store: CLIStore,
  repoPath: string,
  webUrl: string,
  reachableUrls: string[],
  flags?: {
    noStart?: boolean;
    savedProvider?: string;
    stillStarting?: boolean;
    setupComplete?: boolean;
  },
): void {
  // A partial update: the saved sandbox choice must survive a finished run.
  updateConfig({
    version: CLI_VERSION,
    setupComplete: true,
    setupMethod:
      (store.currentState.data.envMethod as "manual" | "infisical") || "manual",
    repoPath,
  });

  store.updateData("setupMode", "selfhost");
  store.updateData("upCodeSandbox", readConfig()?.codeSandbox === true);
  store.updateData("upWebUrl", webUrl);
  store.updateData("upReachableUrls", reachableUrls);
  store.updateData("upApiUrl", `${webUrl}/api/v1`);
  store.updateData("upNoStart", flags?.noStart === true);
  // Services started but never answered within the readiness budget — the
  // finished screen must say so instead of claiming GAIA is running.
  store.updateData("upStillStarting", flags?.stillStarting === true);
  store.updateData("upSetupComplete", flags?.setupComplete === true);
  store.updateData("upSavedProvider", flags?.savedProvider);
  store.updateData("upJoinedDockerGroup", joinedDockerGroupThisRun());
  store.updateData("finished", true);
  store.setStep("Finished");
}

/**
 * `gaia up` — one-command self-hosted setup.
 *
 * Flow: ensure prerequisites (Docker incl. install offer) → resolve target
 * repo (recorded install or fresh clone) → env-setup selfhost pipeline with
 * pre-sourced answers (flags → saved config → defaults) → compose pull-first
 * start → print the URL + browser wizard pointer.
 * @module commands/up/flow
 */

import * as fs from "node:fs";
import * as path from "node:path";
import {
  createUpAnswerResolver,
  DEFAULT_INSTALL_DIR,
  portOverridesFromFlags,
  resolveRecordedInstall,
  type UpFlags,
  validateLlmFlags,
} from "../../lib/answers.js";
import { readConfig, writeConfig } from "../../lib/config.js";
import { runEnvSetup } from "../../lib/env-setup.js";
import { delay, runPortChecks } from "../../lib/flow-utils.js";
import * as git from "../../lib/git.js";
import { checkGit, ensureDocker } from "../../lib/prerequisites.js";
import { startServices } from "../../lib/service-starter.js";
import { CLI_VERSION } from "../../lib/version.js";
import { LOG_BUFFER_LINES } from "../../ui/constants.js";
import type { CLIStore } from "../../ui/store.js";
import { waitForUpReadiness } from "./readiness.js";

const ANSI_ESCAPE_RE = new RegExp(`${String.fromCharCode(27)}\\[[0-9;]*m`, "g");

const GAIA_REPO_URL = "https://github.com/theexperiencecompany/gaia.git";

/** Marker of a developer checkout (as opposed to a plain install). */
function hasMiseToml(repoPath: string): boolean {
  return fs.existsSync(path.join(repoPath, "mise.toml"));
}

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
  store.pushAnswerResolver(
    createUpAnswerResolver({ flags: options, repoPath: targetPath }),
  );

  // 1. Prerequisites — git (needed when cloning) and Docker (with an
  //    interactive install offer on apt-based Linux).
  store.setStep("Prerequisites");
  store.setStatus("Checking system requirements...");
  store.updateData("checks", { git: "pending", docker: "pending" });

  const gitStatus = await checkGit();
  store.updateData("checks", {
    ...store.currentState.data.checks,
    git: gitStatus,
  });

  const needsClone = !fs.existsSync(
    path.join(targetPath, "apps/api/app/config/settings_validator.py"),
  );
  if (gitStatus === "error") {
    if (needsClone) {
      store.setError(
        new Error(
          `Git is required to clone GAIA. Install it from https://git-scm.com/downloads and rerun.`,
        ),
      );
      return;
    }
    // Git missing but install exists — cloning isn't needed; proceed.
    store.updateData("checks", {
      ...store.currentState.data.checks,
      git: "missing",
    });
  }

  try {
    await ensureDocker(store);
  } catch (e) {
    store.setError(e as Error);
    return;
  }

  // 2. Ports — conflict-derived alternatives, then explicit flag overrides
  //    win (user intent beats automatic fallback).
  const portOverrides = await runPortChecks(store);
  if (portOverrides === null) {
    return;
  }
  Object.assign(portOverrides, portOverridesFromFlags(options));

  // 3. Dev-tree guardrail: operating on a checkout that contains mise.toml
  //    but is NOT the recorded install likely means a developer's working
  //    tree — rewriting its .env files would clobber dev config.
  if (
    hasMiseToml(targetPath) &&
    targetPath !== recordedInstall &&
    !options.forceDevTree
  ) {
    store.setError(
      new Error(
        `${targetPath} looks like a developer checkout (contains mise.toml) but is not your recorded GAIA install.\n` +
          "'gaia up' would overwrite its environment files.\n" +
          "Re-run with --force-dev-tree to proceed anyway.",
      ),
    );
    return;
  }

  // 4. Repository — reuse the recorded/existing install or clone fresh.
  store.setStep("Repository Setup");
  if (!needsClone) {
    store.setStatus(`Using existing installation at ${targetPath}...`);
    await delay(500);
  } else {
    store.setStatus("Preparing repository...");
    store.updateData("repoProgress", 0);
    store.updateData("repoPhase", "");
    try {
      await git.setupRepo(targetPath, GAIA_REPO_URL, (progress, phase) => {
        store.updateData("repoProgress", progress);
        if (phase) {
          store.updateData("repoPhase", phase);
          store.setStatus(`${phase}...`);
        } else {
          store.setStatus(
            `Cloning repository to ${targetPath}... ${progress}%`,
          );
        }
      });
    } catch (e) {
      store.setError(
        new Error(
          `Failed to clone GAIA into ${targetPath}: ${(e as Error).message}`,
        ),
      );
      return;
    }
    store.setStatus("Repository ready!");
    await delay(500);
  }

  // 5. Environment — selfhost pipeline with pre-sourced answers; prompts
  //    never block because the answer resolver covers them.
  await runEnvSetup(store, targetPath, "selfhost", portOverrides, {
    llmProvider: options.llmProvider,
    llmKey: options.llmKey,
  });
  if (store.currentState.error) {
    return;
  }

  const webPort = portOverrides[3000] ?? 3000;
  const apiPort = portOverrides[8000] ?? 8000;

  // 6. Start — pull-first fast path, local build fallback.
  if (options.noStart) {
    store.setStep("Finished");
    store.setStatus(
      "Environment ready. Start services later with 'gaia start'.",
    );
    finishUp(store, targetPath, webPort, apiPort, {
      noStart: true,
      customProvider: options.llmProvider === "custom",
    });
    return;
  }

  try {
    await startSelfhostServices(store, targetPath, portOverrides, options);
  } catch (e) {
    store.setError(e as Error);
    return;
  }

  // Compose returning is not the stack answering requests — wait for the API
  // health endpoint and the web app before pointing the user at a browser,
  // otherwise the first click lands on "connection refused". On timeout the
  // finish screen says so honestly and exit stays 0 (services keep running).
  const readiness = await waitForUpReadiness(store, { apiPort, webPort });

  finishUp(store, targetPath, webPort, apiPort, {
    noStart: false,
    customProvider: options.llmProvider === "custom",
    stillStarting: !readiness.ready,
  });
}

/**
 * Compose start with the pull-first fast path: pre-built registry images
 * when possible, local build fallback — unless --build forces a build or
 * --pull restricts to pull-only.
 *
 * @throws Error from the last failed start attempt.
 */
async function startSelfhostServices(
  store: CLIStore,
  repoPath: string,
  portOverrides: Record<number, number>,
  options: UpFlags,
): Promise<void> {
  store.setStep("Project Setup");
  store.updateData("dependencyPhase", "Starting Docker services...");
  store.updateData("dependencyProgress", 0);
  store.updateData("dependencyLogs", []);
  store.updateData("dependencyComplete", false);

  const logHandler = (chunk: string) => {
    const lines = chunk
      .split("\n")
      .map((l) => l.replace(ANSI_ESCAPE_RE, "").trim())
      .filter((l) => l.length > 0);
    if (lines.length === 0) return;
    const current: string[] = store.currentState.data.dependencyLogs || [];
    store.updateData(
      "dependencyLogs",
      [...current, ...lines].slice(-LOG_BUFFER_LINES),
    );
  };
  const onStatus = (status: string) => store.setStatus(status);

  if (options.build) {
    await startServices(
      repoPath,
      "selfhost",
      onStatus,
      portOverrides,
      logHandler,
      {
        build: true,
      },
    );
    store.updateData("dependencyProgress", 100);
    store.updateData("dependencyComplete", true);
    return;
  }

  // Pull pre-built images first (fast); fall back to building locally
  // unless --pull restricted us to pull-only.
  let pullError: Error | null = null;
  try {
    store.setStatus("Pulling pre-built images from registry...");
    await startServices(
      repoPath,
      "selfhost",
      onStatus,
      portOverrides,
      logHandler,
      {
        pull: true,
      },
    );
    store.updateData("dependencyProgress", 100);
    store.updateData("dependencyComplete", true);
    return;
  } catch (e) {
    pullError = e as Error;
  }

  const reason = pullError.message.split("\n")[0] ?? "unknown error";
  if (options.pull) {
    throw new Error(
      `Pulling images failed: ${reason}\nUse --build to build images locally instead.`,
    );
  }
  store.setStatus(
    `Registry pull failed (${reason}) — building images locally (this takes a few minutes)...`,
  );

  try {
    await startServices(
      repoPath,
      "selfhost",
      onStatus,
      portOverrides,
      logHandler,
      {
        build: true,
      },
    );
  } catch (e) {
    throw new Error(`Failed to start services: ${(e as Error).message}`);
  }
  store.updateData("dependencyProgress", 100);
  store.updateData("dependencyComplete", true);
}

/** Record the install and move to the Finished step. */
function finishUp(
  store: CLIStore,
  repoPath: string,
  webPort: number,
  apiPort: number,
  flags?: {
    noStart?: boolean;
    customProvider?: boolean;
    stillStarting?: boolean;
  },
): void {
  writeConfig({
    version: CLI_VERSION,
    setupComplete: true,
    setupMethod:
      (store.currentState.data.envMethod as "manual" | "infisical") || "manual",
    repoPath,
    createdAt: readConfig()?.createdAt ?? new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  });

  store.updateData("setupMode", "selfhost");
  store.updateData("upWebPort", webPort);
  store.updateData("upApiPort", apiPort);
  store.updateData("upNoStart", flags?.noStart === true);
  // Services started but never answered within the readiness budget — the
  // finished screen must say so instead of claiming GAIA is running.
  store.updateData("upStillStarting", flags?.stillStarting === true);
  // Custom providers are runtime-configured; no key was written to .env —
  // the finished screen points at the web wizard instead.
  store.updateData("customProviderNote", flags?.customProvider === true);
  store.updateData("finished", true);
  store.setStep("Finished");
}

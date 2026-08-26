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
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { execa } from "execa";
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

/**
 * Map a raw docker build log line to a human-readable phase label for the
 * TUI spinner. Returns null when the line carries no phase signal.
 *
 * Keep regex intentionally simple — docker buildx output is not machine
 * stable, but `"=> ["` reliably marks a build step. On a 4 GB VM the web
 * build can stall for 30 min with no other output, so any detected step
 * should reassure the user rather than silently spinning.
 */
export function detectBuildPhase(logLine: string): string | null {
  // Build step markers: "=> [stage-1 1/7]" or "=> CACHED [stage-2 3/3]"
  if (logLine.includes("=> [") || logLine.includes("=> CACHED [")) {
    const match = logLine.match(
      /=>\s*(?:CACHED\s*)?\[([^\]]+?)\s+(\d+)\/(\d+)\]/,
    );
    if (match) {
      const stage = match[1] ?? "";
      const cur = match[2];
      const total = match[3];
      // Final stage is the longest; call it out so users don't kill it.
      if (stage.includes("stage-2")) {
        return `Building web — final stage (${cur}/${total}) — please wait, longest step`;
      }
      return `Building web (${cur}/${total}) — this can take 5-30 min on 4 GB RAM, please wait`;
    }
    if (logLine.includes("stage-2")) {
      return "Building web — final stage (please wait, longest step)";
    }
    return "Building images... (this can take 5-30 min on 4 GB RAM, please wait)";
  }
  if (
    logLine.toLowerCase().includes("naming to docker.io") ||
    logLine.toLowerCase().includes("naming to")
  ) {
    return "Build complete — finalizing images...";
  }
  if (logLine.includes("Network gaia")) {
    return "Starting containers...";
  }
  if (
    logLine.includes("Container") &&
    (logLine.includes("Started") || logLine.includes("Created"))
  ) {
    return "Starting containers...";
  }
  return null;
}

/** Marker of a developer checkout (as opposed to a plain install). */
function hasMiseToml(repoPath: string): boolean {
  return fs.existsSync(path.join(repoPath, "mise.toml"));
}

/**
 * Detect whether `apps/web` source has changed since the running `gaia-web`
 * image was built. v1 heuristic: if the container exists and git reports local
 * changes or a recent pull touched `apps/web/`, warn the user to rebuild.
 * Never throws — returns false on any detection failure.
 */
export async function detectWebDrift(repoPath: string): Promise<boolean> {
  // Container must exist; otherwise there is nothing stale.
  try {
    await execa("docker", ["inspect", "gaia-web"]);
  } catch {
    return false;
  }

  // Local modifications to apps/web/
  try {
    const { stdout } = await execa(
      "git",
      ["status", "--porcelain", "--", "apps/web/"],
      { cwd: repoPath },
    );
    if (stdout.trim().length > 0) return true;
  } catch {
    // ignore — try next heuristic
  }

  // Recent pull changed apps/web/ (HEAD@{1} may not exist on fresh clones)
  try {
    const { stdout } = await execa(
      "git",
      ["diff", "--name-only", "HEAD@{1}", "HEAD", "--", "apps/web/"],
      { cwd: repoPath },
    );
    if (stdout.trim().length > 0) return true;
  } catch {
    // HEAD@{1} missing or not a git repo — not drift
  }

  return false;
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

  // Web drift detection (v1): if apps/web source changed since last build and
  // gaia-web container exists, warn to rebuild. Don't auto-rebuild (slow).
  if (!options.build) {
    try {
      const drifted = await detectWebDrift(targetPath);
      if (drifted) {
        store.updateData("webDriftDetected", true);
        // Visible in both TUI (finished screen) and plain summary; also
        // briefly in the status line before it is overwritten by start progress.
        store.setStatus(
          "Web source changed since last build — run 'gaia up --build' to rebuild",
        );
      }
    } catch {
      // never block start on drift check failure
    }
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

  // Auto-open the setup wizard when running interactively on macOS and the
  // stack is actually ready. Non-blocking, errors are ignored — the URL is
  // already printed in both the success screen and the plain summary.
  if (readiness.ready) {
    const isTTY = process.stdin.isTTY === true && process.stdout.isTTY === true;
    if (!options.yes && isTTY && os.platform() === "darwin") {
      const setupUrl = `http://localhost:${webPort}/setup`;
      execFile("open", [setupUrl], () => undefined);
    }
  }
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
    // Surface build-phase labels so the spinner doesn't go silent for minutes
    // on resource-constrained VMs (web build alone can be 30 min on 4 GB RAM).
    for (const line of lines) {
      const phase = detectBuildPhase(line);
      if (phase) {
        store.updateData("dependencyPhase", phase);
        store.setStatus(phase);
      }
    }
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

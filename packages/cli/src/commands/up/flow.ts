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
import {
  createUpAnswerResolver,
  DEFAULT_INSTALL_DIR,
  portOverridesFromFlags,
  resolveRecordedInstall,
  type UpFlags,
  validateLlmFlags,
} from "../../lib/answers.js";
import { readConfig, updateConfig, writeConfig } from "../../lib/config.js";
import { DEFAULT_WEB_PORT, localApiUrl } from "../../lib/endpoints.js";
import { runEnvSetup } from "../../lib/env-setup.js";
import { delay, runPortChecks } from "../../lib/flow-utils.js";
import * as git from "../../lib/git.js";
import { checkGit, ensureDocker } from "../../lib/prerequisites.js";
import { waitForUpReadiness } from "../../lib/readiness.js";
import { detectSetupMode, startServices } from "../../lib/service-starter.js";
import { CLI_VERSION } from "../../lib/version.js";
import { LOG_BUFFER_LINES } from "../../ui/constants.js";
import type { CLIStore } from "../../ui/store.js";

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
    if (
      (await ensureDocker(store, { assumeYes: options.yes === true })) ===
      "relaunch"
    ) {
      return;
    }
  } catch (e) {
    store.setError(e as Error);
    return;
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
  // Record the install before anything else can fail, so a rerun resumes
  // this checkout instead of tripping over it.
  updateConfig({ repoPath: targetPath });

  // 5. Environment — selfhost pipeline with pre-sourced answers; prompts
  //    never block because the answer resolver covers them.
  await runEnvSetup(store, targetPath, "selfhost", portOverrides, {
    llmProvider: options.llmProvider,
    llmKey: options.llmKey,
    domain: options.domain,
  });
  if (store.currentState.error) {
    return;
  }

  const webPort = portOverrides[DEFAULT_WEB_PORT] ?? DEFAULT_WEB_PORT;
  const webUrl = options.domain
    ? `https://${options.domain}`
    : `http://localhost:${webPort}`;

  // 6. Start — pull-first fast path, local build fallback.
  if (options.noStart) {
    store.setStep("Finished");
    store.setStatus(
      "Environment ready. Start services later with 'gaia start'.",
    );
    finishUp(store, targetPath, webUrl, {
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

  // Compose returning is not the stack answering. Probe localhost: the proxy
  // answers there even before a GAIA_DOMAIN resolves. A timeout exits 0.
  const readiness = await waitForUpReadiness(store, {
    apiUrl: localApiUrl("selfhost", portOverrides),
    webPort,
  });

  finishUp(store, targetPath, webUrl, {
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
      const setupUrl = `${webUrl}/setup`;
      execFile("open", [setupUrl], () => undefined);
    }
  }
}

/**
 * Compose start from the published images, or from a local build with --build.
 * A failed start never turns into a build behind the user's back: building is
 * slow and CPU-heavy, and it would hide why the images did not come up.
 *
 * @throws Error naming --build when the images cannot be pulled or started.
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

  if (!options.build) {
    store.setStatus("Pulling GAIA images from the registry...");
  }
  try {
    await startServices(
      repoPath,
      "selfhost",
      onStatus,
      portOverrides,
      logHandler,
      // A rerun keeps the images it has; `gaia update` refreshes them.
      options.build ? { build: true } : { pull: "missing" },
    );
  } catch (e) {
    const reason = (e as Error).message;
    throw new Error(
      options.build
        ? `Failed to build and start services: ${reason}`
        : `Failed to start services from the published images: ${reason}\n` +
            "Check 'gaia logs'. To build the images from this checkout instead, rerun with --build.",
    );
  }
  store.updateData("dependencyProgress", 100);
  store.updateData("dependencyComplete", true);
}

/** Record the install and move to the Finished step. */
function finishUp(
  store: CLIStore,
  repoPath: string,
  webUrl: string,
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
  store.updateData("upWebUrl", webUrl);
  store.updateData("upApiUrl", `${webUrl}/api/v1`);
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

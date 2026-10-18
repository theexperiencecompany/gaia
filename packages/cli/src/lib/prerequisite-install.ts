/**
 * Make Docker (and Git, for the developer commands) available: find what is
 * missing, ask once for all of it (one sudo prompt, not one per tool), install
 * it on apt-based Linux, then make sure this user can reach Docker.
 * @module lib/prerequisite-install
 */

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { execa } from "execa";
import type { CLIStore } from "../ui/store.js";
import {
  type AptActivity,
  aptDownloadTotal,
  aptInstallPackages,
  watchAptActivity,
} from "./apt-activity.js";
import { formatByteProgress, formatBytes } from "./byte-size.js";
import {
  type DockerAccess,
  dockerAccessError,
  getDockerAccess,
} from "./docker-access.js";
import {
  ensureDockerGroupMembership,
  resolveDockerGroupSwitch,
} from "./docker-group.js";
import { watchDockerStart } from "./docker-units.js";
import { newLogPath } from "./logs.js";
import { isInteractive } from "./non-tty.js";
import type {
  DockerInstallStage,
  InstallablePrerequisite,
  InstallProgress,
  InstallStage,
} from "./prerequisite-install.types.js";
import { checkGit, PREREQUISITE_URLS } from "./prerequisites.js";
import type {
  CheckResult,
  DockerReadiness,
  InstallConsentOptions,
} from "./prerequisites.types.js";
import { runAsRoot } from "./root-command.js";

/** Official Docker Engine install script (apt-based distros), per Docker docs. */
const DOCKER_INSTALL_SCRIPT_URL = "https://get.docker.com";
const ORBSTACK_URL = "https://orbstack.dev";
const DOCKER_DESKTOP_MAC_URL =
  "https://docs.docker.com/desktop/install/mac-install/";

/** dpkg's step for docker-ce's setup, which starts the daemon. */
const DOCKER_DAEMON_SETUP = "setting up docker-ce";

const PREREQUISITE_NAMES: Record<InstallablePrerequisite, string> = {
  git: "Git",
  docker: "Docker",
};

/** The one install confirmation the screens render (InstallConfirmStep). */
export const INSTALL_CONFIRM_INPUT = "prerequisite_install_confirm";

/** Store key listing what the confirmation offers to install. */
export const MISSING_PREREQUISITES_KEY = "missingPrerequisites";

/** The user answered no to installing what is missing: nothing failed, the run stops here. */
export class PrerequisiteDeclined extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PrerequisiteDeclined";
  }
}

export function isDebianAptLinux(): boolean {
  return (
    fs.existsSync("/usr/bin/apt-get") || fs.existsSync("/etc/debian_version")
  );
}

function setCheck(
  store: CLIStore,
  name: InstallablePrerequisite,
  result: CheckResult,
): void {
  store.updateData("checks", {
    ...store.currentState.data.checks,
    [name]: result,
  });
}

/** "Git and Docker", "Docker". */
export function joinNames(tools: readonly InstallablePrerequisite[]): string {
  return tools.map((tool) => PREREQUISITE_NAMES[tool]).join(" and ");
}

/** @throws Error naming how to install Docker by hand where the CLI cannot. */
function refuseUnsupportedDockerInstall(): never {
  if (os.platform() === "darwin") {
    // Auto-installing a hypervisor on someone's Mac is too invasive.
    throw new Error(
      "GAIA runs in Docker, which isn't installed yet.\n" +
        `  • OrbStack (lightweight): ${ORBSTACK_URL}\n` +
        `  • Docker Desktop: ${DOCKER_DESKTOP_MAC_URL}\n` +
        "Install either, open it, then run this command again.",
    );
  }
  throw new Error(
    `GAIA runs in Docker, which isn't installed yet. Install it from ${PREREQUISITE_URLS.docker}, then run this command again.`,
  );
}

/**
 * Consent to installing everything missing at once: --yes, else one confirm
 * in the terminal. Never installs without one of the two.
 * @throws Error naming --yes and the manual installs when neither is given.
 */
async function confirmInstall(
  store: CLIStore,
  missing: readonly InstallablePrerequisite[],
  options: InstallConsentOptions,
): Promise<void> {
  if (options.assumeYes) return;
  const names = joinNames(missing);
  if (!isInteractive()) {
    throw new Error(
      `GAIA needs ${names}, and there is no terminal to ask before installing.\n` +
        "Rerun with --yes to install them, or install them first:\n" +
        missing.map((tool) => `  ${PREREQUISITE_URLS[tool]}`).join("\n"),
    );
  }
  for (const tool of missing) setCheck(store, tool, "missing");
  store.updateData(MISSING_PREREQUISITES_KEY, missing);
  const answer = await store.waitForInput(INSTALL_CONFIRM_INPUT);
  if (answer !== "install") {
    throw new PrerequisiteDeclined(
      `Skipped installing ${names}. Install ${missing.length > 1 ? "them" : "it"} (${missing.map((tool) => PREREQUISITE_URLS[tool]).join(", ")}), then run ${options.rerunCommand ? `'${options.rerunCommand}'` : "this command"} again.`,
    );
  }
}

/** What each stage of an install is called on its line under the step. */
const INSTALL_STAGE_LABELS: Record<InstallStage, string> = {
  prepare: "Preparing the install",
  download: "Downloading packages",
  install: "Installing packages",
  start: "Starting Docker",
  check: "Making sure Docker is ready",
};

/** The stages an install goes through, in order. */
export const INSTALL_STAGES: readonly { id: InstallStage; label: string }[] = (
  ["prepare", "download", "install", "start", "check"] as const
).map((id) => ({ id, label: INSTALL_STAGE_LABELS[id] }));

/** "setting up containerd.io" → "containerd.io": the stage's own line already says what dpkg does. */
function dpkgPackage(activity: AptActivity): string | undefined {
  return activity.dpkg?.split(" ").at(-1);
}

async function installGit(
  report: (progress: InstallProgress) => void,
): Promise<void> {
  report({ stage: "prepare", note: "package lists" });
  const logPath = newLogPath("git-install");
  let installing = false;
  const stop = watchAptActivity((activity) => {
    if (!installing) return;
    report(
      activity.dpkg
        ? { stage: "install", note: dpkgPackage(activity) }
        : { stage: "download", note: formatBytes(activity.downloaded) },
    );
  });
  try {
    await runAsRoot("apt-get", ["update"], logPath);
    installing = true;
    report({ stage: "download" });
    await runAsRoot("apt-get", ["install", "-y", "git"], logPath);
  } catch (e) {
    throw new Error(
      `Git installation failed: ${(e as Error).message}\n` +
        `Install it by hand following ${PREREQUISITE_URLS.git}, then run this command again.`,
    );
  } finally {
    stop();
  }
  if ((await checkGit()) !== "success") {
    throw new Error(
      `Git was installed but 'git --version' still fails. Install it by hand following ${PREREQUISITE_URLS.git}, then run this command again.`,
    );
  }
}

/** The stage Docker's install script is entering, from one line of its output; null when the line starts none. */
export function dockerInstallPhase(line: string): DockerInstallStage | null {
  if (line.includes("Executing docker install script")) {
    return { stage: "preparing", detail: "running Docker's script" };
  }
  if (!line.startsWith("+ ")) return null;
  const packages = aptInstallPackages(line);
  if (packages?.includes("docker-ce"))
    return { stage: "downloading", packages };
  if (line.includes("apt-get") && line.includes("update")) {
    return { stage: "preparing", detail: "package lists" };
  }
  if (line.includes("gpg") || line.includes("docker.asc")) {
    return { stage: "preparing", detail: "package source" };
  }
  if (packages) {
    return { stage: "preparing", detail: "what Docker needs" };
  }
  if (line.includes("systemctl")) return { stage: "starting" };
  return null;
}

/** A reporter that never moves back a stage: dpkg sets up more packages after the daemon starts. */
function forwardOnly(
  report: (progress: InstallProgress) => void,
): (progress: InstallProgress) => void {
  const order = INSTALL_STAGES.map((s) => s.id);
  let furthest = 0;
  return (progress) => {
    const at = order.indexOf(progress.stage);
    if (at < furthest) return;
    furthest = at;
    report(progress);
  };
}

/**
 * Report Docker's own install: preparing, then its packages downloading (of
 * the size apt says they are), then dpkg installing them, then the service
 * starting. The script hides apt's output, so the bytes are read from apt's
 * cache and dpkg's log.
 */
function trackDockerInstall(
  reportAny: (progress: InstallProgress) => void,
  logPath: string,
): { onLine: (line: string) => void; stop: () => void } {
  const report = forwardOnly(reportAny);
  let stopWatching = (): void => undefined;
  let stopWatchingUnits: (() => void) | null = null;
  let total: number | null = null;
  // Once dockerd runs, what is left is the rest of the script.
  const startWatchingUnits = (): void => {
    if (stopWatchingUnits) return;
    report({ stage: "start" });
    stopWatchingUnits = watchDockerStart(
      (state) =>
        report(
          state.running
            ? { stage: "check" }
            : { stage: "start", note: state.note },
        ),
      // Only the note is lost: the install itself goes on, and the log says why.
      (error) =>
        fs.appendFileSync(
          logPath,
          `gaia: could not read the Docker services' state: ${error.message}\n`,
        ),
    );
  };
  const show = (activity: AptActivity): void => {
    // docker-ce's setup step is the daemon's first start.
    if (activity.dpkg === DOCKER_DAEMON_SETUP) {
      startWatchingUnits();
      return;
    }
    if (activity.dpkg) {
      report({ stage: "install", note: dpkgPackage(activity) });
      return;
    }
    report({
      stage: "download",
      note:
        total === null
          ? formatBytes(activity.downloaded)
          : formatByteProgress(
              activity.downloaded,
              Math.max(total, activity.downloaded),
              false,
            ),
    });
  };
  const onLine = (line: string): void => {
    const phase = dockerInstallPhase(line);
    if (!phase) return;
    if (phase.stage === "preparing") {
      report({ stage: "prepare", note: phase.detail });
      return;
    }
    stopWatching();
    if (phase.stage === "starting") {
      startWatchingUnits();
      return;
    }
    show({ downloaded: 0, dpkg: null });
    stopWatching = watchAptActivity(show);
    aptDownloadTotal(phase.packages).then(
      (bytes) => {
        total = bytes;
      },
      // Only the bar's total is lost: the install itself goes on, and the log says why.
      (error: unknown) =>
        fs.appendFileSync(
          logPath,
          `gaia: could not read Docker's download size: ${(error as Error).message}\n`,
        ),
    );
  };
  return {
    onLine,
    stop: () => {
      stopWatching();
      stopWatchingUnits?.();
    },
  };
}

/**
 * Run the official Docker Engine convenience script for apt-based distros,
 * downloading it to a temp file so sudo can execute it without a
 * pipe-under-root race. Its output goes to a log.
 */
async function installDocker(
  report: (progress: InstallProgress) => void,
): Promise<void> {
  const scriptPath = path.join(os.tmpdir(), "gaia-docker-install.sh");
  const logPath = newLogPath("docker-install");
  report({ stage: "prepare", note: "Docker's script" });
  await execa("curl", ["-fsSL", DOCKER_INSTALL_SCRIPT_URL, "-o", scriptPath]);
  const tracker = trackDockerInstall(report, logPath);
  try {
    await runAsRoot("sh", [scriptPath], logPath, tracker.onLine);
  } catch (e) {
    throw new Error(
      `Docker installation failed: ${(e as Error).message}\n` +
        `Install it by hand following ${PREREQUISITE_URLS.docker}, then run this command again.`,
    );
  } finally {
    tracker.stop();
  }
}

/** Run one prerequisite under its System Checks row: pending while it runs, failed if it throws. */
async function underCheck<T>(
  store: CLIStore,
  name: InstallablePrerequisite,
  step: () => Promise<T>,
): Promise<T> {
  setCheck(store, name, "pending");
  try {
    const result = await step();
    setCheck(store, name, "success");
    return result;
  } catch (e) {
    setCheck(store, name, "error");
    throw e;
  }
}

/** This user can reach Docker, or the command must relaunch in the docker group. */
async function ensureDockerAccess(
  store: CLIStore,
  access: DockerAccess,
): Promise<DockerReadiness> {
  if (access === "no-permission") {
    store.setStatus("Giving your user access to Docker (the docker group)…");
    await ensureDockerGroupMembership();
    store.updateData("dockerGroupSwitch", await resolveDockerGroupSwitch());
    store.setStatus("Docker access granted. Continuing with it…");
    return "relaunch";
  }
  if (access !== "ready") throw await dockerAccessError(access);
  return "ready";
}

/**
 * Make Git (when needGit) and Docker available. Everything missing is offered
 * in one confirmation, installed on apt-based Linux, and Docker is then made
 * reachable for this user.
 * @throws Error with the manual-install path when something cannot be made available.
 */
export async function ensurePrerequisites(
  store: CLIStore,
  options: InstallConsentOptions & {
    needGit: boolean;
    /** Called once consent is given, as the installs begin. */
    onInstallStart?: (missing: readonly InstallablePrerequisite[]) => void;
    /** Where an install is; by default the store's status line says it. */
    onInstallProgress?: (progress: InstallProgress) => void;
  },
): Promise<DockerReadiness> {
  const gitMissing = options.needGit && (await checkGit()) !== "success";
  let access = await getDockerAccess();
  const missing: InstallablePrerequisite[] = [];
  if (gitMissing) missing.push("git");
  if (access === "not-installed") missing.push("docker");

  const canInstall = os.platform() === "linux" && isDebianAptLinux();
  if (gitMissing && !canInstall) {
    setCheck(store, "git", "error");
    throw new Error(
      `GAIA needs Git, which isn't installed. Install it from ${PREREQUISITE_URLS.git}, then run this command again.`,
    );
  }
  if (access === "not-installed" && !canInstall) {
    setCheck(store, "docker", "error");
    refuseUnsupportedDockerInstall();
  }
  if (missing.length > 0) {
    try {
      await confirmInstall(store, missing, options);
    } catch (e) {
      for (const tool of missing) setCheck(store, tool, "error");
      throw e;
    }
    options.onInstallStart?.(missing);
  }

  const report =
    options.onInstallProgress ??
    ((progress: InstallProgress) =>
      store.setStatus(
        `${INSTALL_STAGE_LABELS[progress.stage]}${progress.note ? ` · ${progress.note}` : ""}…`,
      ));
  if (options.needGit) {
    await underCheck(store, "git", async () => {
      if (gitMissing) await installGit(report);
    });
  }
  return underCheck(store, "docker", async () => {
    if (access === "not-installed") {
      await installDocker(report);
      report({ stage: "check" });
      access = await getDockerAccess();
    }
    return ensureDockerAccess(store, access);
  });
}

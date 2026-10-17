/**
 * Make Git and Docker available: find what is missing, ask once for all of
 * it (one sudo prompt, not one per tool), install it on apt-based Linux, then
 * make sure this user can reach Docker.
 * @module lib/prerequisite-install
 */

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { execa } from "execa";
import type { CLIStore } from "../ui/store.js";
import {
  type DockerAccess,
  dockerAccessError,
  getDockerAccess,
} from "./docker-access.js";
import {
  ensureDockerGroupMembership,
  resolveDockerGroupSwitch,
} from "./docker-group.js";
import { newLogPath } from "./logs.js";
import { isInteractive } from "./non-tty.js";
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

/** The prerequisites the CLI can install, by their System Checks row. */
export type InstallablePrerequisite = "git" | "docker";

const PREREQUISITE_NAMES: Record<InstallablePrerequisite, string> = {
  git: "Git",
  docker: "Docker",
};

/** The one install confirmation the screens render (InstallConfirmStep). */
export const INSTALL_CONFIRM_INPUT = "prerequisite_install_confirm";

/** Store key listing what the confirmation offers to install. */
export const MISSING_PREREQUISITES_KEY = "missingPrerequisites";

function isDebianAptLinux(): boolean {
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
    throw new Error(
      `GAIA needs ${names}. Install ${missing.length > 1 ? "them" : "it"}, then run this command again:\n` +
        missing.map((tool) => `  ${PREREQUISITE_URLS[tool]}`).join("\n"),
    );
  }
}

async function installGit(store: CLIStore): Promise<void> {
  store.setStatus("Installing Git...");
  const logPath = newLogPath("git-install");
  try {
    await runAsRoot("apt-get", ["update"], logPath);
    await runAsRoot("apt-get", ["install", "-y", "git"], logPath);
  } catch (e) {
    throw new Error(
      `Git installation failed: ${(e as Error).message}\n` +
        `Install it by hand following ${PREREQUISITE_URLS.git}, then run this command again.`,
    );
  }
  if ((await checkGit()) !== "success") {
    throw new Error(
      `Git was installed but 'git --version' still fails. Install it by hand following ${PREREQUISITE_URLS.git}, then run this command again.`,
    );
  }
}

/** The step Docker's install script is on, from one line of its output; null when the line names none. */
export function dockerInstallPhase(line: string): string | null {
  if (line.includes("Executing docker install script")) {
    return "Starting Docker's installer";
  }
  if (!line.startsWith("+ ")) return null;
  if (line.includes("docker-ce")) return "Installing Docker";
  if (line.includes("apt-get") && line.includes("update")) {
    return "Updating the package list";
  }
  if (line.includes("gpg") || line.includes("docker.asc")) {
    return "Adding Docker's package source";
  }
  if (line.includes("apt-get") && line.includes("install")) {
    return "Installing what Docker needs";
  }
  if (line.includes("systemctl")) return "Starting Docker";
  return null;
}

/**
 * Run the official Docker Engine convenience script for apt-based distros,
 * downloading it to a temp file so sudo can execute it without a
 * pipe-under-root race. Its output goes to a log; the status names its step.
 */
async function installDocker(store: CLIStore): Promise<void> {
  const scriptPath = path.join(os.tmpdir(), "gaia-docker-install.sh");
  const logPath = newLogPath("docker-install");
  const status = (phase: string) => store.setStatus(`${phase}...`);
  status("Downloading Docker's installer");
  await execa("curl", ["-fsSL", DOCKER_INSTALL_SCRIPT_URL, "-o", scriptPath]);
  try {
    await runAsRoot("sh", [scriptPath], logPath, (line) => {
      const phase = dockerInstallPhase(line);
      if (phase) status(phase);
    });
  } catch (e) {
    throw new Error(
      `Docker installation failed: ${(e as Error).message}\n` +
        `Install it by hand following ${PREREQUISITE_URLS.docker}, then run this command again.`,
    );
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
    store.setStatus("Giving your user access to Docker (the docker group)...");
    await ensureDockerGroupMembership();
    store.updateData("dockerGroupSwitch", await resolveDockerGroupSwitch());
    store.setStatus("Docker access granted. Continuing with it...");
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
  options: InstallConsentOptions & { needGit: boolean },
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
  }

  if (options.needGit) {
    await underCheck(store, "git", async () => {
      if (gitMissing) await installGit(store);
    });
  }
  return underCheck(store, "docker", async () => {
    if (access === "not-installed") {
      await installDocker(store);
      store.setStatus("Docker installed. Checking that it runs...");
      access = await getDockerAccess();
    }
    return ensureDockerAccess(store, access);
  });
}

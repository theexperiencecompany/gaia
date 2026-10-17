import * as fs from "node:fs";
import * as path from "node:path";
import { execa } from "execa";
import type { CLIStore } from "../ui/store.js";
import { COMPOSE_PROJECT_BY_MODE, getProjectPublishedPorts } from "./docker.js";
import { dockerAccessError, getDockerAccess } from "./docker-access.js";
import {
  ensureDockerGroupMembership,
  resolveDockerGroupSwitch,
} from "./docker-group.js";
import {
  DEFAULT_API_PORT,
  DEFAULT_HTTPS_PORT,
  DEFAULT_WEB_PORT,
} from "./endpoints.js";
import type { SetupMode } from "./env-parser.js";
import { newLogPath } from "./logs.js";
import { isInteractive } from "./non-tty.js";
import type {
  CheckResult,
  DockerReadiness,
  InstallConsentOptions,
  PortCheckResult,
} from "./prerequisites.types.js";
import { runAsRoot } from "./root-command.js";

export const PREREQUISITE_URLS = {
  git: "https://git-scm.com/downloads",
  docker: "https://docs.docker.com/get-docker/",
  mise: "https://mise.jdx.dev/getting-started.html",
} as const;

const PORT_SERVICE_MAP: Record<number, string> = {
  8000: "API Server",
  5432: "PostgreSQL",
  6379: "Redis",
  27017: "MongoDB",
  5672: "RabbitMQ",
  15672: "RabbitMQ Management",
  [DEFAULT_WEB_PORT]: "Web Frontend",
  [DEFAULT_HTTPS_PORT]: "Web Frontend (HTTPS)",
  8080: "ChromaDB",
  8083: "Mongo Express",
};

/**
 * Host ports each mode publishes, by default value. Self-host publishes only
 * its proxy; developer mode publishes every infra service plus the native
 * API and web dev servers.
 */
const REQUIRED_HOST_PORTS: Record<SetupMode, readonly number[]> = {
  selfhost: [DEFAULT_WEB_PORT, DEFAULT_HTTPS_PORT],
  developer: [
    DEFAULT_API_PORT,
    5432,
    6379,
    27017,
    5672,
    15672,
    DEFAULT_WEB_PORT,
    8080,
    8083,
  ],
};

/**
 * Port check for a mode's host ports (after overrides). Ports already
 * published by this mode's own compose project count as available, so a
 * rerun or `gaia doctor` against a running stack never reports GAIA itself.
 */
export async function checkModePorts(
  mode: SetupMode,
  overrides: Record<number, number> = {},
): Promise<PortCheckResult[]> {
  const ownPorts = await getProjectPublishedPorts(
    COMPOSE_PROJECT_BY_MODE[mode],
  );
  const effective = REQUIRED_HOST_PORTS[mode].map((p) => overrides[p] ?? p);
  const toCheck = effective.filter((p) => !ownPorts.has(p));
  const results = await checkPortsWithFallback(toCheck);
  const byPort = new Map(results.map((r) => [r.port, r]));
  return effective.map(
    (port) =>
      byPort.get(port) ?? {
        port,
        service: PORT_SERVICE_MAP[port] || `Port ${port}`,
        available: true,
      },
  );
}

export async function checkGit(): Promise<CheckResult> {
  try {
    await execa("git", ["--version"]);
    return "success";
  } catch {
    return "error";
  }
}

export async function checkMise(): Promise<CheckResult> {
  try {
    await execa("mise", ["--version"]);
    return "success";
  } catch {
    return "missing";
  }
}

/** Official Docker Engine install script (apt-based distros), per Docker docs. */
const DOCKER_INSTALL_SCRIPT_URL = "https://get.docker.com";

const ORBSTACK_URL = "https://orbstack.dev";
const DOCKER_DESKTOP_MAC_URL =
  "https://docs.docker.com/desktop/install/mac-install/";

/** The prerequisites the CLI can install, by their System Checks row. */
type InstallablePrerequisite = "git" | "docker";

const PREREQUISITE_NAMES: Record<InstallablePrerequisite, string> = {
  git: "Git",
  docker: "Docker",
};

/** Input ids of the install confirmations the screens render (InstallConfirmStep). */
export const INSTALL_CONFIRM_INPUT = {
  git: "git_install_confirm",
  docker: "docker_install_confirm",
} as const satisfies Record<InstallablePrerequisite, string>;

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

/** Run a prerequisite step under its System Checks row: pending while it runs, failed if it throws. */
async function underCheck<T>(
  store: CLIStore,
  name: InstallablePrerequisite,
  step: () => Promise<T>,
): Promise<T> {
  setCheck(store, name, "pending");
  try {
    return await step();
  } catch (e) {
    setCheck(store, name, "error");
    throw e;
  }
}

/**
 * Consent to installing a missing prerequisite: --yes, else a confirm in the
 * terminal. Never installs without one of the two.
 * @throws Error naming --yes and the manual install when neither is given.
 */
async function confirmInstall(
  store: CLIStore,
  tool: InstallablePrerequisite,
  options: InstallConsentOptions,
  manualInstall: string,
): Promise<void> {
  if (options.assumeYes) return;
  const name = PREREQUISITE_NAMES[tool];
  if (!isInteractive()) {
    throw new Error(
      `${name} is required but not installed, and there is no terminal to confirm installation.\n` +
        `Rerun with --yes to install it, or install ${name} first:\n` +
        `  ${manualInstall}`,
    );
  }
  store.setStatus(`${name} is not installed.`);
  const confirmed = await store.waitForInput(INSTALL_CONFIRM_INPUT[tool]);
  if (confirmed !== "install") {
    throw new Error(
      `${name} is required to continue. Install it from ${PREREQUISITE_URLS[tool]} and rerun.`,
    );
  }
}

/**
 * Ensure git is installed. Linux apt installs it on consent (a TTY confirm,
 * or --yes), the same way {@link ensureDocker} installs Docker.
 * @throws Error with remediation copy when git cannot be made available.
 */
export async function ensureGit(
  store: CLIStore,
  options: InstallConsentOptions = {},
): Promise<void> {
  await underCheck(store, "git", () => makeGitAvailable(store, options));
  setCheck(store, "git", "success");
}

async function makeGitAvailable(
  store: CLIStore,
  options: InstallConsentOptions,
): Promise<void> {
  if ((await checkGit()) === "success") return;
  const os = await import("node:os");
  if (os.platform() !== "linux" || !isDebianAptLinux()) {
    throw new Error(
      `Git is required but not installed. Install it from ${PREREQUISITE_URLS.git} and rerun.`,
    );
  }
  await confirmInstall(store, "git", options, "sudo apt-get install -y git");
  store.setStatus("Installing Git...");
  const logPath = newLogPath("git-install");
  try {
    await runAsRoot("apt-get", ["update"], logPath);
    await runAsRoot("apt-get", ["install", "-y", "git"], logPath);
  } catch (e) {
    throw new Error(
      `Git installation failed: ${(e as Error).message}\n` +
        `Install it manually following ${PREREQUISITE_URLS.git} and rerun.`,
    );
  }
  if ((await checkGit()) !== "success") {
    throw new Error(
      `Git was installed but 'git --version' still fails. Install it manually following ${PREREQUISITE_URLS.git} and rerun.`,
    );
  }
}

/**
 * Ensure Docker is installed, running, and usable by this user.
 * Linux apt installs the official engine on consent (a TTY confirm, or
 * --yes), then grants the non-root user the docker group. macOS never
 * auto-installs (points at OrbStack / Docker Desktop); a stopped daemon is an
 * actionable start-Docker error.
 * @throws Error with remediation copy when Docker cannot be made available.
 */
export async function ensureDocker(
  store: CLIStore,
  options: InstallConsentOptions = {},
): Promise<DockerReadiness> {
  return underCheck(store, "docker", () => makeDockerAvailable(store, options));
}

async function makeDockerAvailable(
  store: CLIStore,
  options: InstallConsentOptions,
): Promise<DockerReadiness> {
  let access = await getDockerAccess();

  if (access === "not-installed") {
    const os = await import("node:os");
    const platform = os.platform();

    if (platform === "darwin") {
      // Auto-installing a hypervisor on someone's Mac is too invasive —
      // surface both lightweight (OrbStack) and official options instead.
      throw new Error(
        "GAIA runs in Docker, which isn't installed yet.\n" +
          `  • OrbStack (lightweight): ${ORBSTACK_URL}\n` +
          `  • Docker Desktop: ${DOCKER_DESKTOP_MAC_URL}\n` +
          "Install either, open it, then run this command again.",
      );
    }

    if (platform !== "linux" || !isDebianAptLinux()) {
      throw new Error(
        `GAIA runs in Docker, which isn't installed yet. Install it from ${PREREQUISITE_URLS.docker}, then run this command again.`,
      );
    }

    await confirmInstall(
      store,
      "docker",
      options,
      `curl -fsSL ${DOCKER_INSTALL_SCRIPT_URL} | sudo sh`,
    );
    await installDockerLinux(store);
    store.setStatus("Docker installed. Checking that it runs...");
    access = await getDockerAccess();
  }

  if (access === "no-permission") {
    store.setStatus("Giving your user access to Docker (the docker group)...");
    await ensureDockerGroupMembership();
    store.updateData("dockerGroupSwitch", await resolveDockerGroupSwitch());
    store.setStatus("Docker access granted. Continuing with it...");
    return "relaunch";
  }

  if (access !== "ready") throw await dockerAccessError(access);

  setCheck(store, "docker", "success");
  return "ready";
}

/** The step Docker's install script is on, from one line of its output; null when the line names none. */
export function dockerInstallPhase(line: string): string | null {
  if (line.includes("Executing docker install script")) {
    return "Starting Docker's installer";
  }
  if (!line.startsWith("+ ")) return null;
  if (line.includes("docker-ce")) return "Installing Docker Engine";
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
async function installDockerLinux(store: CLIStore): Promise<void> {
  const os = await import("node:os");
  const scriptPath = path.join(os.tmpdir(), "gaia-docker-install.sh");
  const logPath = newLogPath("docker-install");
  const status = (phase: string) =>
    store.setStatus(`Installing Docker (a few minutes): ${phase}...`);
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
export async function installMise(): Promise<boolean> {
  const os = await import("node:os");
  const platform = os.platform();

  if (platform === "win32") {
    try {
      await execa("powershell", [
        "-Command",
        "irm https://mise.jdx.dev/install.ps1 | iex",
      ]);
      return true;
    } catch {
      return false;
    }
  }

  try {
    await execa("sh", ["-c", "curl https://mise.jdx.dev/install.sh | sh"]);
    return true;
  } catch {
    return false;
  }
}

async function checkPortsWithFallback(
  ports: number[],
): Promise<PortCheckResult[]> {
  const net = await import("node:net");
  const results: PortCheckResult[] = [];

  const isPortFree = (port: number): Promise<boolean> => {
    return new Promise((resolve) => {
      const server = net.createServer();
      server.once("error", () => resolve(false));
      server.once("listening", () => {
        server.close(() => resolve(true));
      });
      server.listen(port);
    });
  };

  for (const port of ports) {
    const service = PORT_SERVICE_MAP[port] || `Port ${port}`;
    const free = await isPortFree(port);

    if (free) {
      results.push({ port, service, available: true });
    } else {
      const usedBy = await getPortUser(port);
      const alternative = await findNextAvailablePort(
        port + 1,
        port + 100,
        isPortFree,
      );
      results.push({
        port,
        service,
        available: false,
        usedBy,
        alternative: alternative || undefined,
      });
    }
  }

  return results;
}

async function getPortUser(port: number): Promise<string | undefined> {
  const os = await import("node:os");
  const platform = os.platform();

  if (platform === "win32") {
    try {
      const { stdout } = await execa("netstat", ["-ano", "-p", "TCP"]);
      const lines = stdout.trim().split("\n");
      for (const line of lines) {
        if (line.includes(`:${port}`) && line.includes("LISTENING")) {
          const parts = line.trim().split(/\s+/);
          const pid = parts[parts.length - 1];
          if (pid) {
            try {
              const { stdout: taskOut } = await execa("tasklist", [
                "/FI",
                `PID eq ${pid}`,
                "/FO",
                "CSV",
                "/NH",
              ]);
              const name = taskOut.trim().split(",")[0]?.replace(/"/g, "");
              return name || `PID ${pid}`;
            } catch {
              return `PID ${pid}`;
            }
          }
        }
      }
    } catch {
      // netstat may not be available
    }
    return undefined;
  }

  try {
    const { stdout } = await execa("lsof", [
      "-i",
      `:${port}`,
      "-sTCP:LISTEN",
      "-P",
      "-n",
    ]);
    const lines = stdout.trim().split("\n");
    if (lines.length > 1) {
      const parts = lines[1]?.split(/\s+/);
      return parts?.[0] || undefined;
    }
  } catch {
    // lsof may not be available or port not in use
  }
  return undefined;
}

async function findNextAvailablePort(
  startPort: number,
  maxPort: number,
  isPortFree: (port: number) => Promise<boolean>,
): Promise<number | null> {
  for (let port = startPort; port <= maxPort; port++) {
    if (await isPortFree(port)) {
      return port;
    }
  }
  return null;
}

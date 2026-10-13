import * as fs from "node:fs";
import * as path from "node:path";
import { execa } from "execa";
import type { CLIStore } from "../ui/store.js";
import { COMPOSE_PROJECT_BY_MODE, getProjectPublishedPorts } from "./docker.js";
import {
  ensureDockerGroupMembership,
  isDockerSocketPermissionError,
} from "./docker-group.js";
import {
  DEFAULT_API_PORT,
  DEFAULT_HTTPS_PORT,
  DEFAULT_WEB_PORT,
} from "./endpoints.js";
import type { SetupMode } from "./env-parser.js";
import type {
  CheckResult,
  DockerReadiness,
  EnsureDockerOptions,
  PortCheckResult,
  PrerequisiteInfo,
} from "./prerequisites.types.js";

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

export async function checkDockerDetailed(): Promise<PrerequisiteInfo> {
  let installed = false;
  let working = false;
  let errorMessage: string | undefined;

  try {
    await execa("docker", ["--version"]);
    installed = true;
  } catch {
    return {
      name: "Docker",
      installUrl: PREREQUISITE_URLS.docker,
      installed: false,
      working: false,
      errorMessage: "Docker is not installed",
    };
  }

  let permissionDenied = false;
  try {
    await execa("docker", ["info"], { timeout: 5000 });
    working = true;
  } catch (e) {
    permissionDenied = isDockerSocketPermissionError(e);
    errorMessage = permissionDenied
      ? "Docker is running but this user cannot reach its socket (not in the docker group)."
      : "Docker is installed but the daemon is not running. Please start Docker Desktop or the Docker daemon.";
  }

  return {
    name: "Docker",
    installUrl: PREREQUISITE_URLS.docker,
    installed,
    working,
    permissionDenied,
    errorMessage,
  };
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

function isDebianAptLinux(): boolean {
  return (
    fs.existsSync("/usr/bin/apt-get") || fs.existsSync("/etc/debian_version")
  );
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
  options: EnsureDockerOptions = {},
): Promise<DockerReadiness> {
  store.updateData("checks", {
    ...store.currentState.data.checks,
    docker: "pending",
  });

  let info = await checkDockerDetailed();

  if (!info.installed) {
    const os = await import("node:os");
    const platform = os.platform();

    if (platform === "darwin") {
      // Auto-installing a hypervisor on someone's Mac is too invasive —
      // surface both lightweight (OrbStack) and official options instead.
      throw new Error(
        "Docker is required but not installed.\n" +
          `  • OrbStack (lightweight): ${ORBSTACK_URL}\n` +
          `  • Docker Desktop: ${DOCKER_DESKTOP_MAC_URL}\n` +
          "Install either, then rerun this command.",
      );
    }

    if (platform !== "linux" || !isDebianAptLinux()) {
      throw new Error(
        `Docker is required but not installed. Install it from ${PREREQUISITE_URLS.docker} and rerun.`,
      );
    }

    if (!options.assumeYes) {
      if (!(process.stdin.isTTY === true && process.stdout.isTTY === true)) {
        // Fail loud instead of silently continuing without Docker.
        throw new Error(
          "Docker is required but not installed, and there is no terminal to confirm installation.\n" +
            "Rerun with --yes to install it, or install Docker Engine first:\n" +
            `  curl -fsSL ${DOCKER_INSTALL_SCRIPT_URL} | sudo sh`,
        );
      }

      store.setStatus("Docker is not installed.");
      const confirmed = await store.waitForInput("docker_install_confirm");
      if (confirmed !== "install") {
        throw new Error(
          "Docker is required to continue. Install it from " +
            `${PREREQUISITE_URLS.docker} and rerun.`,
        );
      }
    }

    store.setStatus(
      "Installing Docker Engine (this can take several minutes)...",
    );
    await installDockerLinux();
    store.setStatus("Docker installed. Verifying...");
    info = await checkDockerDetailed();
  }

  if (info.permissionDenied) {
    store.setStatus("Granting this user access to Docker (docker group)...");
    await ensureDockerGroupMembership();
    store.updateData("relaunchWithDockerGroup", true);
    store.setStatus("Docker access granted — restarting to pick it up...");
    return "relaunch";
  }

  if (!info.working) {
    store.updateData("checks", {
      ...store.currentState.data.checks,
      docker: "error",
    });
    store.updateData("dockerError", info.errorMessage);
    throw new Error(
      info.errorMessage ||
        "Docker is not running. Start Docker, then rerun this command.",
    );
  }

  store.updateData("checks", {
    ...store.currentState.data.checks,
    docker: "success",
  });
  return "ready";
}

/**
 * Run the official Docker Engine convenience script for apt-based distros,
 * downloading it to a temp file so sudo can execute it without a
 * pipe-under-root race. stdio is inherited so sudo can prompt for a password.
 */
async function installDockerLinux(): Promise<void> {
  const os = await import("node:os");
  const scriptPath = path.join(os.tmpdir(), "gaia-docker-install.sh");
  await execa("curl", ["-fsSL", DOCKER_INSTALL_SCRIPT_URL, "-o", scriptPath]);

  const isRoot = typeof process.getuid === "function" && process.getuid() === 0;
  try {
    if (isRoot) {
      await execa("sh", [scriptPath], { stdio: "inherit" });
    } else {
      await execa("sudo", ["sh", scriptPath], { stdio: "inherit" });
    }
  } catch (e) {
    throw new Error(
      `Docker installation failed: ${(e as Error).message}\n` +
        `Install manually following ${PREREQUISITE_URLS.docker} and rerun.`,
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

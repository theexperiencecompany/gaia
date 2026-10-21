import * as net from "node:net";
import { execa } from "execa";
import { COMPOSE_PROJECT_BY_MODE, getProjectPublishedPorts } from "./docker.js";
import {
  DEFAULT_API_PORT,
  DEFAULT_HTTPS_PORT,
  DEFAULT_WEB_PORT,
} from "./endpoints.js";
import type { SetupMode } from "./env-parser.js";
import type { CheckResult, PortCheckResult } from "./prerequisites.types.js";

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
  const results: PortCheckResult[] = [];
  for (const defaultPort of REQUIRED_HOST_PORTS[mode]) {
    const port = overrides[defaultPort] ?? defaultPort;
    const service = PORT_SERVICE_MAP[defaultPort] || `Port ${port}`;
    results.push(
      ownPorts.has(port)
        ? { defaultPort, port, service, available: true }
        : await checkPort(defaultPort, port, service),
    );
  }
  return results;
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

function isPortFree(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => resolve(false));
    server.once("listening", () => {
      server.close(() => resolve(true));
    });
    server.listen(port);
  });
}

/** Whether the host port is free; if not, who holds it and the next free one above it. */
async function checkPort(
  defaultPort: number,
  port: number,
  service: string,
): Promise<PortCheckResult> {
  if (await isPortFree(port)) {
    return { defaultPort, port, service, available: true };
  }
  const alternative = await findNextAvailablePort(port + 1, port + 100);
  return {
    defaultPort,
    port,
    service,
    available: false,
    usedBy: await getPortUser(port),
    alternative: alternative || undefined,
  };
}

/** A Docker container publishing the port: lsof can't see docker-proxy's socket without root. */
async function dockerContainerOnPort(
  port: number,
): Promise<string | undefined> {
  try {
    const { stdout } = await execa("docker", [
      "ps",
      "--filter",
      `publish=${port}`,
      "--format",
      "{{.Names}}",
    ]);
    const name = stdout.trim().split("\n")[0];
    return name ? `Docker container ${name}` : undefined;
  } catch {
    // Docker not answering: fall back to lsof.
    return undefined;
  }
}

async function getPortUser(port: number): Promise<string | undefined> {
  const container = await dockerContainerOnPort(port);
  if (container) return container;
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
): Promise<number | null> {
  for (let port = startPort; port <= maxPort; port++) {
    if (await isPortFree(port)) {
      return port;
    }
  }
  return null;
}

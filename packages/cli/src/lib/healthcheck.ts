import {
  COMPOSE_PROJECT_BY_MODE,
  type ContainerStatus,
  getContainerStatuses,
} from "./docker.js";
import {
  type DockerAccess,
  type DockerProblem,
  describeDockerProblem,
  getDockerAccess,
} from "./docker-access.js";
import type { SetupMode } from "./env-parser.js";

export interface ServiceStatus {
  name: string;
  port: number;
  status: "up" | "down" | "unknown";
  latency?: number;
  details?: string;
}

/** Every service developer mode publishes on the host. */
const DEVELOPER_SERVICES = [
  { name: "API", port: 8000, type: "http" as const, path: "/health" },
  { name: "Web", port: 3000, type: "http" as const, path: "/" },
  { name: "PostgreSQL", port: 5432, type: "tcp" as const },
  { name: "Redis", port: 6379, type: "tcp" as const },
  { name: "MongoDB", port: 27017, type: "tcp" as const },
  { name: "RabbitMQ", port: 5672, type: "tcp" as const },
  { name: "ChromaDB", port: 8080, type: "tcp" as const },
];

/** Probe the developer stack's host ports (after infra/docker/.env overrides). */
export async function checkDeveloperServices(
  portOverrides: Record<number, number>,
): Promise<ServiceStatus[]> {
  return Promise.all(
    DEVELOPER_SERVICES.map((service) => {
      const port = portOverrides[service.port] ?? service.port;
      return service.type === "http"
        ? checkHttpService(service.name, port, service.path)
        : checkTcpService(service.name, port);
    }),
  );
}

async function checkHttpService(
  name: string,
  port: number,
  path: string,
): Promise<ServiceStatus> {
  const start = Date.now();
  try {
    const res = await fetch(`http://localhost:${port}${path}`, {
      signal: AbortSignal.timeout(5000),
    });
    const latency = Date.now() - start;
    return {
      name,
      port,
      status: res.ok ? "up" : "down",
      latency,
      details: res.ok ? `HTTP ${res.status}` : `HTTP ${res.status} (error)`,
    };
  } catch {
    return { name, port, status: "down", details: "Connection failed" };
  }
}

async function checkTcpService(
  name: string,
  port: number,
): Promise<ServiceStatus> {
  const net = await import("node:net");
  const start = Date.now();

  return new Promise((resolve) => {
    const socket = new net.Socket();
    socket.setTimeout(3000);

    socket.on("connect", () => {
      const latency = Date.now() - start;
      socket.destroy();
      resolve({ name, port, status: "up", latency });
    });

    socket.on("timeout", () => {
      socket.destroy();
      resolve({ name, port, status: "down" });
    });

    socket.on("error", () => {
      socket.destroy();
      resolve({ name, port, status: "down" });
    });

    socket.connect(port, "localhost");
  });
}

/** Docker as `gaia status` reports it: why it is unusable, or the project's containers. */
export interface DockerStatus {
  access: DockerAccess;
  /** What is wrong and how to fix it; absent when access is "ready". */
  problem?: DockerProblem;
  containers: ContainerStatus[];
}

export async function getDockerStatus(mode: SetupMode): Promise<DockerStatus> {
  const access = await getDockerAccess();
  if (access !== "ready") {
    return {
      access,
      problem: await describeDockerProblem(access),
      containers: [],
    };
  }
  const containers = await getContainerStatuses(COMPOSE_PROJECT_BY_MODE[mode]);
  return { access, containers };
}

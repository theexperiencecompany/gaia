import {
  COMPOSE_PROJECT_BY_MODE,
  getContainerStatuses,
  isDockerRunning,
} from "./docker.js";
import { DEFAULT_WEB_PORT } from "./endpoints.js";
import type { SetupMode } from "./env-parser.js";

export interface ServiceStatus {
  name: string;
  port: number;
  status: "up" | "down" | "unknown";
  latency?: number;
  details?: string;
}

// Developer mode publishes every service on the host.
const DEVELOPER_SERVICES = [
  { name: "API", port: 8000, type: "http" as const, path: "/health" },
  { name: "Web", port: 3000, type: "http" as const, path: "/" },
  { name: "PostgreSQL", port: 5432, type: "tcp" as const },
  { name: "Redis", port: 6379, type: "tcp" as const },
  { name: "MongoDB", port: 27017, type: "tcp" as const },
  { name: "RabbitMQ", port: 5672, type: "tcp" as const },
  { name: "ChromaDB", port: 8080, type: "tcp" as const },
];

// Self-host publishes only the proxy; the API answers behind it at /api/v1
// and the infra services are reported by container state instead.
const SELFHOST_SERVICES = [
  {
    name: "API",
    port: DEFAULT_WEB_PORT,
    type: "http" as const,
    path: "/api/v1/ping",
  },
  { name: "Web", port: DEFAULT_WEB_PORT, type: "http" as const, path: "/" },
];

export async function checkAllServices(
  mode: SetupMode,
  portOverrides?: Record<number, number>,
): Promise<ServiceStatus[]> {
  const catalog = mode === "selfhost" ? SELFHOST_SERVICES : DEVELOPER_SERVICES;
  const services = catalog.map((service) => ({
    ...service,
    port: portOverrides?.[service.port] ?? service.port,
  }));

  const promises = services.map((service) =>
    service.type === "http"
      ? checkHttpService(service.name, service.port, service.path)
      : checkTcpService(service.name, service.port),
  );

  return Promise.all(promises);
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

export async function getDockerStatus(mode: SetupMode): Promise<{
  running: boolean;
  containers: Awaited<ReturnType<typeof getContainerStatuses>>;
}> {
  const running = await isDockerRunning();
  if (!running) {
    return { running: false, containers: [] };
  }
  const containers = await getContainerStatuses(COMPOSE_PROJECT_BY_MODE[mode]);
  return { running: true, containers };
}

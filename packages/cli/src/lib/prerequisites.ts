import { execa } from "execa";

export type CheckResult = "success" | "error" | "missing" | "pending";

export interface PortCheckResult {
  port: number;
  service: string;
  available: boolean;
  usedBy?: string;
  alternative?: number;
}

const PORT_SERVICE_MAP: Record<number, string> = {
  8000: "API Server",
  5432: "PostgreSQL",
  6379: "Redis",
  27017: "MongoDB",
  5672: "RabbitMQ",
  3000: "Web Frontend",
  8080: "ChromaDB",
  8083: "Mongo Express",
};

export async function checkGit(): Promise<CheckResult> {
  try {
    await execa("git", ["--version"]);
    return "success";
  } catch {
    return "error";
  }
}

export async function checkDocker(): Promise<CheckResult> {
  try {
    await execa("docker", ["--version"]);
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
  try {
    await execa("sh", [
      "-c",
      "curl https://mise.jdx.dev/install.sh | sh",
    ]);
    return true;
  } catch {
    return false;
  }
}

export async function checkPorts(
  ports: number[],
): Promise<{ available: boolean; conflict?: number }> {
  try {
    const net = await import("node:net");

    const checkPort = (port: number): Promise<boolean> => {
      return new Promise((resolve) => {
        const server = net.createServer();
        server.once("error", () => {
          resolve(false);
        });
        server.once("listening", () => {
          server.close(() => resolve(true));
        });
        server.listen(port);
      });
    };

    for (const port of ports) {
      const isFree = await checkPort(port);
      if (!isFree) {
        return { available: false, conflict: port };
      }
    }

    return { available: true };
  } catch {
    return { available: true };
  }
}

export async function checkPortsWithFallback(
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

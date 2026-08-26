import { execa } from "execa";

export interface ContainerStatus {
  name: string;
  status: "running" | "stopped" | "not_found";
  health?: string;
}

const GAIA_CONTAINERS = [
  "gaia-backend",
  "gaia-web",
  "chromadb",
  "postgres",
  "redis",
  "mongo",
  "rabbitmq",
  "arq_worker",
];

export async function getContainerStatuses(): Promise<ContainerStatus[]> {
  try {
    const { stdout } = await execa("docker", [
      "inspect",
      "--format",
      "{{.Name}}|{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
      ...GAIA_CONTAINERS,
    ]);

    const inspected = new Map<string, ContainerStatus>();
    for (const line of stdout.trim().split("\n")) {
      if (!line) continue;
      const [rawName, status, health] = line.split("|");
      const name = rawName?.replace(/^\//, "") ?? "";
      inspected.set(name, {
        name,
        status: status === "running" ? "running" : "stopped",
        health: health !== "none" ? health : undefined,
      });
    }

    return GAIA_CONTAINERS.map(
      (name) => inspected.get(name) ?? { name, status: "not_found" },
    );
  } catch {
    const promises = GAIA_CONTAINERS.map(
      async (name): Promise<ContainerStatus> => {
        try {
          const { stdout } = await execa("docker", [
            "inspect",
            "--format",
            "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
            name,
          ]);
          const [status, health] = stdout.trim().split("|");
          return {
            name,
            status: status === "running" ? "running" : "stopped",
            health: health !== "none" ? health : undefined,
          };
        } catch {
          return { name, status: "not_found" };
        }
      },
    );

    return Promise.all(promises);
  }
}

export async function isDockerRunning(): Promise<boolean> {
  try {
    await execa("docker", ["info"]);
    return true;
  } catch {
    return false;
  }
}

/** One container of a Docker Compose project, as reported by `docker ps`. */
export interface ComposeContainerInfo {
  /** Compose service name (label `com.docker.compose.service`). */
  service: string;
  /** Raw Docker state, e.g. "running", "restarting", "exited". */
  state: string;
}

/**
 * List all containers of a Docker Compose project (including stopped ones),
 * keyed by compose service name. Throws when the daemon is unreachable so
 * callers can distinguish "daemon down" from "container missing".
 */
export async function getComposeProjectContainers(
  project: string,
): Promise<ComposeContainerInfo[]> {
  const { stdout } = await execa("docker", [
    "ps",
    "-a",
    "--filter",
    `label=com.docker.compose.project=${project}`,
    "--format",
    '{{.Label "com.docker.compose.service"}}|{{.State}}',
  ]);

  return parseComposePsOutput(stdout);
}

function parseComposePsOutput(stdout: string): ComposeContainerInfo[] {
  const containers: ComposeContainerInfo[] = [];
  for (const line of stdout.trim().split("\n")) {
    if (!line) continue;
    const [service, state] = line.split("|");
    if (!service || !state) continue;
    containers.push({ service, state });
  }
  return containers;
}

/** Absolute path of the daemon's data root (`docker info .DockerRootDir`). */
export async function getDockerRootDir(): Promise<string> {
  const { stdout } = await execa("docker", [
    "info",
    "--format",
    "{{.DockerRootDir}}",
  ]);
  const dir = stdout.trim();
  if (!dir) throw new Error("docker info returned an empty DockerRootDir");
  return dir;
}

/** Raw `df -k <path>` output for the given directory. */
export async function getDiskFreeKb(path: string): Promise<string> {
  const { stdout } = await execa("df", ["-k", path]);
  return stdout;
}

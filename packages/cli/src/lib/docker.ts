import * as fs from "node:fs";
import * as os from "node:os";
import { execa } from "execa";
import type { SetupMode } from "./env-parser.js";

export const DOCKER_SOCKET_PATH = "/var/run/docker.sock";

export interface ContainerStatus {
  name: string;
  status: "running" | "stopped" | "not_found";
  health?: string;
}

/** Docker Compose project name for each setup mode (`name:` in its file). */
export const COMPOSE_PROJECT_BY_MODE: Record<SetupMode, ComposeProject> = {
  selfhost: "gaia-selfhost",
  developer: "gaia-dev",
};

export type ComposeProject = "gaia-selfhost" | "gaia-dev";

const HEALTH_IN_STATUS_RE = /\((healthy|unhealthy|health: starting)\)/;

/** Status of every container in a compose project, named by compose service. */
export async function getContainerStatuses(
  project: ComposeProject,
): Promise<ContainerStatus[]> {
  const containers = await getComposeProjectContainers(project);
  return containers.map((c) => ({
    name: c.service,
    status: c.state === "running" ? "running" : "stopped",
    health: c.health,
  }));
}

/**
 * Host ports the running containers of a compose project publish. A port held
 * by GAIA's own stack is not a conflict: a rerun must keep it, not move off it.
 */
export async function getProjectPublishedPorts(
  project: ComposeProject,
): Promise<Set<number>> {
  const { stdout } = await execa("docker", [
    "ps",
    "--filter",
    `label=com.docker.compose.project=${project}`,
    "--format",
    "{{.Ports}}",
  ]);
  const ports = new Set<number>();
  for (const match of stdout.matchAll(/:(\d+)->/g)) {
    ports.add(Number(match[1]));
  }
  return ports;
}

/**
 * Group owning the Docker socket as containers see it, for the self-host
 * sandbox's `group_add`. Linux bind-mounts the host socket as is; Docker
 * Desktop and OrbStack expose it root-owned (gid 0) inside their VM.
 */
export function getDockerSocketGid(): number {
  if (os.platform() !== "linux" || !fs.existsSync(DOCKER_SOCKET_PATH)) {
    return 0;
  }
  return fs.statSync(DOCKER_SOCKET_PATH).gid;
}

/** One container of a Docker Compose project, as reported by `docker ps`. */
export interface ComposeContainerInfo {
  /** Compose service name (label `com.docker.compose.service`). */
  service: string;
  /** Raw Docker state, e.g. "running", "restarting", "exited". */
  state: string;
  /** Healthcheck verdict when the service defines one, e.g. "healthy". */
  health?: string;
}

/**
 * List all containers of a Docker Compose project (including stopped ones),
 * keyed by compose service name. Containers carry no fixed names, so the
 * project label is the stable handle that also keeps a dev and a self-host
 * stack apart on one host. Throws when the daemon is unreachable so
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
    '{{.Label "com.docker.compose.service"}}|{{.State}}|{{.Status}}',
  ]);

  return parseComposePsOutput(stdout);
}

function parseComposePsOutput(stdout: string): ComposeContainerInfo[] {
  const containers: ComposeContainerInfo[] = [];
  for (const line of stdout.trim().split("\n")) {
    if (!line) continue;
    const [service, state, statusText] = line.split("|");
    if (!service || !state) continue;
    const health = statusText?.match(HEALTH_IN_STATUS_RE)?.[1];
    containers.push(health ? { service, state, health } : { service, state });
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

/**
 * First Docker Engine major with `volume-subpath` mounts (API 1.45), which the
 * code sandbox uses to give each user's container only that user's files.
 */
const MIN_CODE_SANDBOX_ENGINE_MAJOR = 26;

/** The daemon's Docker Engine version, e.g. "29.1.3". */
async function getDockerServerVersion(): Promise<string> {
  const { stdout } = await execa("docker", [
    "version",
    "--format",
    "{{.Server.Version}}",
  ]);
  return stdout.trim();
}

/** Throw unless the daemon can isolate code-sandbox users (see MIN_CODE_SANDBOX_ENGINE_MAJOR). */
export async function assertEngineSupportsCodeSandbox(): Promise<void> {
  const version = await getDockerServerVersion();
  const major = Number.parseInt(version, 10);
  if (Number.isNaN(major) || major < MIN_CODE_SANDBOX_ENGINE_MAJOR) {
    throw new Error(
      `The code sandbox needs Docker Engine ${MIN_CODE_SANDBOX_ENGINE_MAJOR} or newer (this daemon is ${version || "unknown"}): ` +
        "it mounts only each user's own files into their sandbox. Upgrade Docker, or run `gaia up --no-code-sandbox` and save an E2B key instead.",
    );
  }
}

/** Whether a named Docker volume exists; throws when the daemon is unreachable. */
export async function dockerVolumeExists(name: string): Promise<boolean> {
  const { stdout } = await execa("docker", [
    "volume",
    "ls",
    "--quiet",
    "--filter",
    `name=^${name}$`,
  ]);
  return stdout.trim().split("\n").includes(name);
}

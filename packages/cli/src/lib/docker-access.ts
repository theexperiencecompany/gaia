/**
 * Whether this process can use Docker, and if not, the one reason and fix a
 * person can act on. Every command that talks to Docker asks here, so a
 * refused socket never reads as "Docker is not running".
 * @module lib/docker-access
 */

import * as os from "node:os";
import { execa } from "execa";
import {
  DOCKER_GROUP,
  isDockerSocketPermissionError,
  isUserInDockerGroup,
} from "./docker-group.js";

/** How `docker info` answered this process. */
export type DockerAccess =
  | "ready"
  | "not-installed"
  | "not-running"
  /** The daemon runs, but its socket refuses this user (no docker group in this session). */
  | "no-permission";

/** `docker info` waits this long for a daemon before calling it not running. */
const DOCKER_INFO_TIMEOUT_MS = 5000;

const ORBSTACK_URL = "https://orbstack.dev";

export async function getDockerAccess(): Promise<DockerAccess> {
  try {
    await execa("docker", ["info"], { timeout: DOCKER_INFO_TIMEOUT_MS });
    return "ready";
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return "not-installed";
    }
    return isDockerSocketPermissionError(error)
      ? "no-permission"
      : "not-running";
  }
}

/** What is wrong and what to do about it, for a Docker that is not ready. */
export interface DockerProblem {
  summary: string;
  fix: string;
}

/**
 * The plain-words problem behind a non-ready access state. Async because a
 * refused socket's fix depends on whether the user already joined the group.
 */
export async function describeDockerProblem(
  access: Exclude<DockerAccess, "ready">,
): Promise<DockerProblem> {
  const mac = os.platform() === "darwin";
  switch (access) {
    case "not-installed":
      return {
        summary: "Docker isn't installed",
        fix: mac
          ? `Install OrbStack (${ORBSTACK_URL}) or Docker Desktop, open it, then try again.`
          : "Run 'gaia up': it offers to install Docker for you.",
      };
    case "not-running":
      return {
        summary: "Docker isn't running",
        fix: mac
          ? "Open OrbStack or Docker Desktop, then try again."
          : "Start it with 'sudo systemctl start docker', then try again.",
      };
    case "no-permission":
      return {
        summary: "Docker is running, but your user can't use it yet",
        fix: (await isUserInDockerGroup())
          ? `Your user just joined the '${DOCKER_GROUP}' group. Log out and back in (or run 'newgrp ${DOCKER_GROUP}' in this terminal), then try again.`
          : `Run 'sudo usermod -aG ${DOCKER_GROUP} $USER', log out and back in, then try again.`,
      };
  }
}

/** One error a command can throw when it needs Docker and cannot use it. */
export async function dockerAccessError(
  access: Exclude<DockerAccess, "ready">,
): Promise<Error> {
  const problem = await describeDockerProblem(access);
  return new Error(`${problem.summary}.\n${problem.fix}`);
}

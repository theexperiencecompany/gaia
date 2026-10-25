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
  /** The daemon is there but `docker info` didn't answer in time (a busy or stuck daemon). */
  | "not-responding"
  /** The daemon runs, but its socket refuses this user (no docker group in this session). */
  | "no-permission";

/** A healthy daemon answers `docker info` in under a second; a busy host can take several. */
const DOCKER_INFO_TIMEOUT_MS = 20_000;

const ORBSTACK_URL = "https://orbstack.dev";

/** The fix wherever something gaia up would install is missing. */
export const GAIA_UP_INSTALLS =
  "Run 'gaia up': it installs everything GAIA needs.";

export async function getDockerAccess(): Promise<DockerAccess> {
  try {
    await execa("docker", ["info"], { timeout: DOCKER_INFO_TIMEOUT_MS });
    return "ready";
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return "not-installed";
    }
    if ((error as { timedOut?: boolean }).timedOut === true) {
      return "not-responding";
    }
    return isDockerSocketPermissionError(error)
      ? "no-permission"
      : "not-running";
  }
}

/** What is wrong and what to do about it, for a Docker that is not ready. */
export interface DockerProblem {
  /** The state alone, for a row already labelled Docker: "isn't installed". */
  state: string;
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
        state: "isn't installed",
        fix: mac
          ? `Install OrbStack (${ORBSTACK_URL}) or Docker Desktop, open it, then try again.`
          : GAIA_UP_INSTALLS,
      };
    case "not-running":
      return {
        summary: "Docker isn't running",
        state: "isn't running",
        fix: mac
          ? "Open OrbStack or Docker Desktop, then try again."
          : "Start it with 'sudo systemctl start docker', then try again.",
      };
    case "not-responding":
      return {
        summary: "Docker isn't answering",
        state: "isn't answering",
        fix: mac
          ? "It may still be starting. Wait a minute and try again, or restart OrbStack or Docker Desktop."
          : "It may still be starting. Wait a minute and try again, or restart it with 'sudo systemctl restart docker'.",
      };
    case "no-permission":
      return {
        summary: "Docker is running, but your user can't use it yet",
        state: "is running, but your user can't use it yet",
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

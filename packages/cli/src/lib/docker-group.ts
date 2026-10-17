/**
 * Docker socket access for a non-root Linux user.
 *
 * Docker's install script never adds the invoking user to the `docker` group,
 * and a group granted with usermod only reaches processes started afterwards.
 * So the CLI grants the group, finishes the current UI, and relaunches the
 * same command in the docker group — one command still runs end to end.
 * @module lib/docker-group
 */

import { spawn } from "node:child_process";
import * as os from "node:os";
import { execa } from "execa";
import { newLogPath } from "./logs.js";
import { runAsRoot } from "./root-command.js";

export const DOCKER_GROUP = "docker";

/** Set in the relaunched process so a still-denied socket fails loud, not loops. */
const RELAUNCHED_ENV = "GAIA_DOCKER_GROUP_RELAUNCHED";

/** The step the first process was in, so the relaunch's output reads as one run. */
const RESUMED_STEP_ENV = "GAIA_RESUMED_STEP";

/** The step this process continues from a docker-group relaunch, if it is one. */
export function resumedStep(): string | undefined {
  return process.env[RESUMED_STEP_ENV] || undefined;
}

/**
 * True in the process a docker-group relaunch started: this run added the
 * user to the group, so the user's own shell lacks it until a new login.
 */
export function joinedDockerGroupThisRun(): boolean {
  return process.env[RELAUNCHED_ENV] === "1";
}

/** True when the group database lists this user in the docker group; a new login may still be needed. */
export async function isUserInDockerGroup(): Promise<boolean> {
  const { stdout } = await execa("id", ["-nG", os.userInfo().username]);
  return stdout.split(/\s+/).includes(DOCKER_GROUP);
}

/** True when `docker` failed because the socket refused this user. */
export function isDockerSocketPermissionError(error: unknown): boolean {
  const stderr = (error as { stderr?: unknown }).stderr;
  return (
    typeof stderr === "string" &&
    stderr.toLowerCase().includes("permission denied")
  );
}

/**
 * Add the current user to the docker group (via sudo) unless the group
 * database already lists them — e.g. Docker was installed earlier and the
 * login session predates the grant.
 * @throws Error when this is already the relaunched process, or sudo fails.
 */
export async function ensureDockerGroupMembership(): Promise<void> {
  if (process.env[RELAUNCHED_ENV] === "1") {
    throw new Error(
      `Still no access to the Docker socket after joining the '${DOCKER_GROUP}' group.\n` +
        "Check the socket's group with 'ls -l /var/run/docker.sock', then log out and back in and rerun.",
    );
  }
  if (await isUserInDockerGroup()) return;
  const user = os.userInfo().username;
  try {
    await runAsRoot(
      "usermod",
      ["-aG", DOCKER_GROUP, user],
      newLogPath("docker-group"),
    );
  } catch (e) {
    throw new Error(
      `Could not add ${user} to the '${DOCKER_GROUP}' group: ${(e as Error).message}\n` +
        `Run 'sudo usermod -aG ${DOCKER_GROUP} ${user}', log out and back in, then rerun.`,
    );
  }
}

/** How the relaunch enters the docker group (see {@link resolveDockerGroupSwitch}). */
export type DockerGroupSwitch = "sg" | "sudo";

/** An environment variable name sudo's --preserve-env list can carry. */
const ENV_NAME_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;

/** True when `command` resolves on PATH; a non-zero `command -v` means absent. */
async function isOnPath(command: string): Promise<boolean> {
  try {
    await execa("sh", ["-c", 'command -v "$1"', "sh", command]);
    return true;
  } catch {
    return false;
  }
}

/** True when sudo lets this user run the CLI with docker as its primary group. */
async function sudoCanSwitchGroup(): Promise<boolean> {
  try {
    await execa("sudo", ["-l", "-g", DOCKER_GROUP, "--", process.execPath]);
    return true;
  } catch {
    return false;
  }
}

/**
 * Pick how to re-run this command in the docker group: sg where the system
 * ships it (Ubuntu 26.04 does not), else sudo -g, which runs as this same
 * user with docker as the primary group.
 * @throws Error telling the user to start a new login session when neither can.
 */
export async function resolveDockerGroupSwitch(): Promise<DockerGroupSwitch> {
  if (await isOnPath("sg")) return "sg";
  if (await sudoCanSwitchGroup()) return "sudo";
  throw new Error(
    `Docker access was granted, but this login session predates it and cannot pick it up ('sg' is missing and sudo cannot switch to the '${DOCKER_GROUP}' group).\n` +
      `Log out and back in (or run 'newgrp ${DOCKER_GROUP}'), then rerun this command.`,
  );
}

/** POSIX single-quote one argument for `sh -c`. */
function shellQuote(arg: string): string {
  return `'${arg.replaceAll("'", `'\\''`)}'`;
}

/** The program and arguments that run `argv` in the docker group via `via`. */
function groupSwitchCommand(
  via: DockerGroupSwitch,
  argv: readonly string[],
  env: NodeJS.ProcessEnv,
): [file: string, args: string[]] {
  if (via === "sg") {
    return ["sg", [DOCKER_GROUP, "-c", argv.map(shellQuote).join(" ")]];
  }
  // sudo resets the environment; name every variable so it carries through.
  const names = Object.keys(env).filter((name) => ENV_NAME_RE.test(name));
  return [
    "sudo",
    [`--preserve-env=${names.join(",")}`, "-g", DOCKER_GROUP, "--", ...argv],
  ];
}

/**
 * Re-run this exact command with the docker group active and exit with its
 * status. Call only after the UI has released the terminal.
 */
export function relaunchWithDockerGroup(
  currentStep: string,
  via: DockerGroupSwitch,
): Promise<never> {
  const env = {
    ...process.env,
    [RELAUNCHED_ENV]: "1",
    [RESUMED_STEP_ENV]: currentStep,
  };
  const [file, args] = groupSwitchCommand(
    via,
    [process.execPath, ...process.argv.slice(1)],
    env,
  );
  const child = spawn(file, args, { stdio: "inherit", env });
  return new Promise((_resolve, reject) => {
    child.on("error", reject);
    child.on("exit", (code, signal) => {
      process.exit(code ?? (signal ? 1 : 0));
    });
  });
}

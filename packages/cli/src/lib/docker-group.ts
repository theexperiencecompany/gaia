/**
 * Docker socket access for a non-root Linux user.
 *
 * Docker's install script never adds the invoking user to the `docker` group,
 * and a group granted with usermod only reaches processes started afterwards.
 * So the CLI grants the group, finishes the current UI, and relaunches the
 * same command in the docker group — one command still runs end to end. Any
 * later command run from a session that predates the grant relaunches the
 * same way, so no terminal needs a new login.
 * @module lib/docker-group
 */

import { spawn } from "node:child_process";
import { constants, promises as fs } from "node:fs";
import * as os from "node:os";
import { execa } from "execa";
import { DOCKER_SOCKET_PATH } from "./docker.js";
import { newLogPath } from "./logs.js";
import { runAsRoot } from "./root-command.js";
import type { RunSubstep } from "./run-steps.types.js";

export const DOCKER_GROUP = "docker";

/** Set in the relaunched process so a still-denied socket fails loud, not loops. */
const RELAUNCHED_ENV = "GAIA_DOCKER_GROUP_RELAUNCHED";

/** The step the first process was in, so the relaunch's output reads as one run. */
const RESUMED_STEP_ENV = "GAIA_RESUMED_STEP";

/** The steps the first process began, so the relaunch's timers and labels carry on from there. */
const RESUMED_STEPS_ENV = "GAIA_RESUMED_STEPS";

/** The step this process continues from a docker-group relaunch, if it is one. */
export function resumedStep(): string | undefined {
  return process.env[RESUMED_STEP_ENV] || undefined;
}

/** What a relaunch carries over of a step the first process began. */
export interface ResumedStep {
  /** Epoch ms. */
  startedAt: number;
  /** What it was called while it ran, e.g. "Installing Docker". */
  label: string;
  /** What the first process would have called it done, e.g. "Docker installed". */
  doneLabel: string;
  minor?: boolean;
  /** Its lines as they stood, so the relaunch carries on from the same one. */
  substeps?: RunSubstep[];
}

/** Step id -> the step as the first process left it, after a docker-group relaunch; empty otherwise. */
export function resumedSteps(): Record<string, ResumedStep> {
  const raw = process.env[RESUMED_STEPS_ENV];
  return raw ? (JSON.parse(raw) as Record<string, ResumedStep>) : {};
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
 * How this command can re-run in the docker group: sg where the system ships
 * it (Ubuntu 26.04 does not), else sudo -g, which runs as this same user with
 * docker as the primary group; null when neither can.
 */
async function findDockerGroupSwitch(): Promise<DockerGroupSwitch | null> {
  if (await isOnPath("sg")) return "sg";
  if (await sudoCanSwitchGroup()) return "sudo";
  return null;
}

/**
 * Pick how to re-run this command in the docker group.
 * @throws Error telling the user to start a new login session when neither sg nor sudo can.
 */
export async function resolveDockerGroupSwitch(): Promise<DockerGroupSwitch> {
  const via = await findDockerGroupSwitch();
  if (via) return via;
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

/** Where a run that relaunches mid-way had got to, so the relaunch carries on from there. */
export interface RelaunchResume {
  step: string;
  steps: Record<string, ResumedStep>;
}

/**
 * Re-run this exact command with the docker group active and exit with its
 * status. Call only after the UI has released the terminal.
 */
export function relaunchWithDockerGroup(
  via: DockerGroupSwitch,
  resume?: RelaunchResume,
): Promise<never> {
  const env = {
    ...process.env,
    [RELAUNCHED_ENV]: "1",
    ...(resume && {
      [RESUMED_STEP_ENV]: resume.step,
      [RESUMED_STEPS_ENV]: JSON.stringify(resume.steps),
    }),
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

/** True when Docker's socket refuses this process: absent, or open to it, is false. */
async function dockerSocketRefusesUs(): Promise<boolean> {
  try {
    await fs.access(DOCKER_SOCKET_PATH, constants.R_OK | constants.W_OK);
    return false;
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    if (code === "ENOENT") return false;
    if (code === "EACCES") return true;
    throw error;
  }
}

/**
 * Re-run this command in the docker group when the user has joined it but
 * this login session predates that, so Docker's socket would refuse it.
 * Returns when no relaunch is needed, or none is possible: then the command's
 * own Docker error says to log out and back in.
 */
export async function relaunchIfDockerGroupPending(): Promise<void> {
  if (os.platform() !== "linux" || process.env[RELAUNCHED_ENV] === "1") return;
  // DOCKER_HOST points at another daemon, whose access is not the group's.
  if (process.env.DOCKER_HOST) return;
  if (!(await dockerSocketRefusesUs())) return;
  if (!(await isUserInDockerGroup())) return;
  const via = await findDockerGroupSwitch();
  if (via) await relaunchWithDockerGroup(via);
}

/**
 * Docker socket access for a non-root Linux user.
 *
 * Docker's install script never adds the invoking user to the `docker` group,
 * and a group granted with usermod only reaches processes started afterwards.
 * So the CLI grants the group, finishes the current UI, and relaunches the
 * same command under `sg docker` — one command still runs end to end.
 * @module lib/docker-group
 */

import { spawn } from "node:child_process";
import * as os from "node:os";
import { execa } from "execa";

const DOCKER_GROUP = "docker";

/** Set in the relaunched process so a still-denied socket fails loud, not loops. */
const RELAUNCHED_ENV = "GAIA_DOCKER_GROUP_RELAUNCHED";

/** The step the first process was in, so the relaunch's output reads as one run. */
const RESUMED_STEP_ENV = "GAIA_RESUMED_STEP";

/** The step this process continues from a docker-group relaunch, if it is one. */
export function resumedStep(): string | undefined {
  return process.env[RESUMED_STEP_ENV] || undefined;
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
  const user = os.userInfo().username;
  const { stdout } = await execa("id", ["-nG", user]);
  if (stdout.split(/\s+/).includes(DOCKER_GROUP)) return;
  try {
    await execa("sudo", ["usermod", "-aG", DOCKER_GROUP, user], {
      stdio: "inherit",
    });
  } catch (e) {
    throw new Error(
      `Could not add ${user} to the '${DOCKER_GROUP}' group: ${(e as Error).message}\n` +
        `Run 'sudo usermod -aG ${DOCKER_GROUP} ${user}', log out and back in, then rerun.`,
    );
  }
}

/** POSIX single-quote one argument for `sh -c`. */
function shellQuote(arg: string): string {
  return `'${arg.replaceAll("'", `'\\''`)}'`;
}

/**
 * Re-run this exact command with the docker group active and exit with its
 * status. Call only after the UI has released the terminal.
 */
export function relaunchWithDockerGroup(currentStep: string): Promise<never> {
  const command = [process.execPath, ...process.argv.slice(1)]
    .map(shellQuote)
    .join(" ");
  const child = spawn("sg", [DOCKER_GROUP, "-c", command], {
    stdio: "inherit",
    env: {
      ...process.env,
      [RELAUNCHED_ENV]: "1",
      [RESUMED_STEP_ENV]: currentStep,
    },
  });
  return new Promise((_resolve, reject) => {
    child.on("error", reject);
    child.on("exit", (code, signal) => {
      process.exit(code ?? (signal ? 1 : 0));
    });
  });
}

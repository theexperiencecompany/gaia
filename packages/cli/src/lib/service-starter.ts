import { execa } from "execa";
import * as fs from "fs";
import * as path from "path";
import { botComposeFile, botService, writeBotsEnv } from "./bots.js";
import { runCommand } from "./child-process.js";
import { ComposeError } from "./compose-failure.js";
import type { ComposePhase } from "./compose-progress.types.js";
import {
  type ComposeRunOptions,
  type ComposeRunResult,
  runCompose,
} from "./compose-run.js";
import { readConfig } from "./config.js";
import { stopDeveloperProcesses } from "./dev-processes.js";
import {
  assertEngineSupportsCodeSandbox,
  dockerVolumeExists,
} from "./docker.js";
import { dockerAccessError, getDockerAccess } from "./docker-access.js";
import type { SetupMode } from "./env-parser.js";
import { portOverridesToDockerEnv } from "./env-writer.js";
import { assertBuildableInstall, detectSetupMode } from "./install-root.js";
import { DEV_DOCKER_DIR, SELFHOST_COMPOSE_FILE, selfhostDir } from "./paths.js";
import {
  measurePull,
  readComposeServices,
  servicesInStartOrder,
} from "./pull-size.js";

/** Rebuilds an install's images from source; named when an image is missing. */
const REBUILD_COMMAND = "gaia start --build";

export interface StopServicesOptions {
  forcePorts?: boolean;
  /** Uninstalling: remove the images too, and the volumes (all data) when asked. */
  remove?: { volumes: boolean };
}

/** `docker compose down` for a stop, or for an uninstall when options.remove is set. */
export function composeDownArgs(options?: StopServicesOptions): string[] {
  if (!options?.remove) return ["down"];
  return [
    "down",
    "--rmi",
    "all",
    "--remove-orphans",
    ...(options.remove.volumes ? ["--volumes"] : []),
  ];
}

/** `--env-file .env` when the compose folder has one (compose resolves it against the run's cwd). */
export function getEnvFileArgs(dockerDir: string): string[] {
  const envPath = path.join(dockerDir, ".env");
  if (fs.existsSync(envPath)) {
    return ["--env-file", ".env"];
  }
  return [];
}

export interface StartServicesOptions {
  build?: boolean;
  /**
   * Image pull policy for `up`: "missing" pulls only absent images (first
   * start); "always" refreshes every tag (`gaia update`, `gaia start --pull`).
   */
  pull?: "always" | "missing";
  /** The command a missing-image error tells the user to build with. */
  rebuildCommand?: string;
}

/** Progress callback for a compose start: the phase line and the finished steps. */
export type StartProgress = NonNullable<ComposeRunOptions["onProgress"]>;

/** Default ceiling for `gaia start`, in minutes. */
const DEFAULT_START_TIMEOUT_MIN = 60;

/**
 * Resolve the `docker compose up` timeout in milliseconds.
 *
 * A pull-based start takes minutes, but `--build` (docker-compose.build.yml) on a
 * resource-constrained VM can spend 30+ minutes on the web production build alone. The
 * default ceiling covers that slow path while still catching a genuinely stuck build;
 * override with GAIA_START_TIMEOUT_MIN, or 0 to disable.
 */
function resolveStartTimeoutMs(): number | undefined {
  // Number("") and Number("  ") are 0, which would silently disable the
  // timeout. Treat a blank value as unset and fall back to the default.
  const raw = process.env.GAIA_START_TIMEOUT_MIN?.trim();
  const overrideMin = raw ? Number(raw) : Number.NaN;
  const timeoutMin =
    Number.isFinite(overrideMin) && overrideMin >= 0
      ? overrideMin
      : DEFAULT_START_TIMEOUT_MIN;
  return timeoutMin === 0 ? undefined : timeoutMin * 60 * 1000;
}

/**
 * Compose files for a self-host install. The base file is image-only; building,
 * the Docker-socket code sandbox and each chat bot are explicit override files.
 * The sandbox and bots come from the saved config, so a restart or update can
 * never silently drop (or add) one.
 */
export function selfhostComposeFiles(
  options: { build?: boolean } = {},
): string[] {
  const config = readConfig();
  const files = [SELFHOST_COMPOSE_FILE];
  if (options.build) files.push("docker-compose.build.yml");
  if (config?.codeSandbox === true) files.push("docker-compose.sandbox.yml");
  files.push(...(config?.bots ?? []).map(botComposeFile));
  return files;
}

export function composeFileArgs(files: string[]): string[] {
  return files.flatMap((file) => ["-f", file]);
}

/** The volume every code sandbox shared before per-user isolation. */
const LEGACY_SANDBOX_VOLUME = "gaia-sandbox-workspace";
const LEGACY_SANDBOX_MOUNT = "/legacy-sandbox-workspace";

/**
 * One-shot copy of the pre-isolation shared sandbox volume into per-user
 * workspaces, mounted read-only; the script's report makes reruns no-ops.
 */
function legacySandboxMigrationArgs(
  files: string[],
  envArgs: string[],
): string[] {
  return [
    "compose",
    ...composeFileArgs(files),
    ...envArgs,
    "run",
    "--rm",
    "--no-deps",
    "-v",
    `${LEGACY_SANDBOX_VOLUME}:${LEGACY_SANDBOX_MOUNT}:ro`,
    "gaia-backend",
    "python",
    "-m",
    "app.scripts.migrate_legacy_sandbox_workspace",
    "--legacy-root",
    LEGACY_SANDBOX_MOUNT,
  ];
}

/** The `docker compose ... up` arguments (after `compose`) for self-host mode. */
function buildSelfhostUpArgs(
  files: string[],
  envArgs: string[],
  options?: StartServicesOptions,
): string[] {
  const upArgs = [
    ...composeFileArgs(files),
    ...envArgs,
    "up",
    "-d",
    "--remove-orphans",
  ];
  // Without --no-build compose silently builds any image it cannot pull from source.
  upArgs.push(options?.build ? "--build" : "--no-build");
  if (options?.pull) upArgs.push("--pull", options.pull);
  return upArgs;
}

export async function startServices(
  repoPath: string,
  setupMode: SetupMode,
  onStatus?: (status: string) => void,
  portOverrides?: Record<number, number>,
  onProgress?: StartProgress,
  options?: StartServicesOptions,
): Promise<ComposeRunResult> {
  if (setupMode !== "selfhost") {
    onStatus?.("Developer mode must run in foreground.");
    throw new Error(
      "Developer mode runs in foreground. Use 'gaia dev' or 'gaia dev full' instead of 'gaia start'.",
    );
  }

  onStatus?.(options?.build ? "Building GAIA from source…" : "Starting GAIA…");

  const dockerComposePath = selfhostDir(repoPath);
  const dockerEnv =
    portOverrides && Object.keys(portOverrides).length > 0
      ? portOverridesToDockerEnv(portOverrides)
      : undefined;
  const config = readConfig();
  if (config?.codeSandbox === true) await assertEngineSupportsCodeSandbox();
  // Re-copies the bot key and public URL, which `gaia up` or a restore may have changed.
  if (config?.bots?.length) writeBotsEnv(repoPath);
  const files = selfhostComposeFiles({ build: options?.build });
  if (options?.build) assertBuildableInstall(repoPath);
  const envArgs = getEnvFileArgs(dockerComposePath);

  const composeArgs = [...composeFileArgs(files), ...envArgs];
  const services = await readComposeServices(
    dockerComposePath,
    composeArgs,
    dockerEnv,
  );
  const pullSize = options?.build
    ? undefined
    : await measurePull(services, { always: options?.pull === "always" });
  const result = await runCompose(
    buildSelfhostUpArgs(files, envArgs, options),
    {
      cwd: dockerComposePath,
      env: dockerEnv,
      timeoutMs: resolveStartTimeoutMs(),
      logName: options?.build ? "compose-build" : "compose-up",
      rebuildCommand: options?.rebuildCommand ?? REBUILD_COMMAND,
      onProgress,
      pullSize,
      services: servicesInStartOrder(services),
    },
  ).catch(async (error: unknown) => {
    throw await withServiceLogTail(error, composeArgs, dockerComposePath);
  });
  if (await dockerVolumeExists(LEGACY_SANDBOX_VOLUME)) {
    onStatus?.("Moving code-sandbox files into per-user workspaces…");
    await runCommand("docker", legacySandboxMigrationArgs(files, envArgs), {
      cwd: dockerComposePath,
      env: dockerEnv,
    });
  }
  onStatus?.("GAIA's services are running.");
  return result;
}

/** How many of a failed service's last log lines an error quotes. */
const FAILED_SERVICE_LOG_LINES = 8;

/**
 * Add the failed service's own last log lines to a compose error that names
 * one (an unhealthy container); its words say why far better than compose's.
 */
async function withServiceLogTail(
  error: unknown,
  composeArgs: string[],
  cwd: string,
): Promise<unknown> {
  if (!(error instanceof ComposeError) || !error.failure.service) return error;
  const { stdout } = await execa(
    "docker",
    [
      "compose",
      ...composeArgs,
      "logs",
      "--no-color",
      "--no-log-prefix",
      "--tail",
      String(FAILED_SERVICE_LOG_LINES),
      error.failure.service,
    ],
    { cwd },
  );
  const logTail = stdout.split("\n").filter((line) => line.trim());
  return new ComposeError({ ...error.failure, logTail }, error.logPath);
}

/** `docker compose` plus the self-host install's files and env file, run from dockerDir. */
export function selfhostComposeArgs(dockerDir: string): string[] {
  return [
    "compose",
    ...composeFileArgs(selfhostComposeFiles()),
    ...getEnvFileArgs(dockerDir),
  ];
}

/** Run a one-off command in a fresh container of a self-host service. */
export async function runSelfhostOneOff(
  repoPath: string,
  service: string,
  command: string[],
  onLog?: (chunk: string) => void,
): Promise<void> {
  const dockerComposePath = selfhostDir(repoPath);
  await runCommand(
    "docker",
    [
      ...selfhostComposeArgs(dockerComposePath),
      "run",
      "--rm",
      "--no-deps",
      service,
      ...command,
    ],
    { cwd: dockerComposePath, onLog },
  );
}

/** The self-host services that run GAIA's own images (GAIA_VERSION). */
const SELFHOST_APP_SERVICES = ["gaia-backend", "arq_worker", "gaia-web"];

/**
 * Pull GAIA's images (enabled bots included) at one tag without touching
 * running containers, so a tag that does not exist fails before anything
 * about the install changes.
 */
export async function pullSelfhostImages(
  repoPath: string,
  version: string,
  onProgress?: StartProgress,
): Promise<void> {
  const dockerComposePath = selfhostDir(repoPath);
  const composeArgs = [
    ...composeFileArgs(selfhostComposeFiles()),
    ...getEnvFileArgs(dockerComposePath),
  ];
  const services = [
    ...SELFHOST_APP_SERVICES,
    ...(readConfig()?.bots ?? []).map(botService),
  ];
  // The shell environment outranks the compose env file in compose interpolation.
  const env = { GAIA_VERSION: version };
  await runCompose([...composeArgs, "pull", ...services], {
    cwd: dockerComposePath,
    env,
    logName: "compose-pull",
    rebuildCommand: "gaia up --build",
    onProgress,
    pullSize: await measurePull(
      await readComposeServices(dockerComposePath, composeArgs, env),
      { only: services, always: true },
    ),
  });
}

export async function stopServices(
  repoPath: string,
  onStatus?: (status: string) => void,
  portOverrides?: Record<number, number>,
  options?: StopServicesOptions,
  /** Each phase of compose's stop, for a step that shows its services; else onStatus gets its label. */
  onPhase?: (phase: ComposePhase) => void,
): Promise<void> {
  const [mode, access] = await Promise.all([
    detectSetupMode(repoPath),
    getDockerAccess(),
  ]);
  const dockerComposePath =
    mode === "selfhost"
      ? selfhostDir(repoPath)
      : path.join(repoPath, DEV_DOCKER_DIR);
  if (access === "ready") {
    onStatus?.("Stopping GAIA's containers…");
    const envArgs = getEnvFileArgs(dockerComposePath);
    const fileArgs =
      mode === "selfhost" ? composeFileArgs(selfhostComposeFiles()) : [];
    await runCompose([...fileArgs, ...envArgs, ...composeDownArgs(options)], {
      cwd: dockerComposePath,
      logName: "compose-down",
      rebuildCommand: REBUILD_COMMAND,
      onProgress: (phase) =>
        onPhase ? onPhase(phase) : onStatus?.(phase.label),
    });
  } else if (mode === "selfhost") {
    // Self-host runs only in Docker: "stopped" would be a lie.
    throw await dockerAccessError(access);
  } else if (access === "no-permission") {
    throw await dockerAccessError(access);
  }

  // In selfhost mode everything runs in Docker, no local processes to kill
  if (mode !== "selfhost") {
    await stopDeveloperProcesses(
      repoPath,
      onStatus,
      portOverrides,
      options?.forcePorts,
    );
  }
  onStatus?.("All services stopped.");
}

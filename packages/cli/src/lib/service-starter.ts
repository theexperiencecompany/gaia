import { execa } from "execa";
import * as fs from "fs";
import * as path from "path";
import { botComposeFile, botService, writeBotsEnv } from "./bots.js";
import { ComposeError } from "./compose-failure.js";
import {
  type ComposeRunOptions,
  type ComposeRunResult,
  runCompose,
} from "./compose-run.js";
import { readConfig, updateConfig } from "./config.js";
import {
  assertEngineSupportsCodeSandbox,
  dockerVolumeExists,
} from "./docker.js";
import { dockerAccessError, getDockerAccess } from "./docker-access.js";
import type { SetupMode } from "./env-parser.js";
import { portOverridesToDockerEnv } from "./env-writer.js";
import { homeRelative } from "./paths.js";
import { measurePull } from "./pull-size.js";
import { BUNDLE_MANIFEST } from "./selfhost-bundle.js";

const delay = (ms: number): Promise<void> =>
  new Promise((r) => setTimeout(r, ms));

export const DEV_LOG_FILE = "dev-start.log";
export const DEV_PID_FILE = ".gaia-dev.pid";

/** Rebuilds an install's images from source; named when an image is missing. */
const REBUILD_COMMAND = "gaia start --build";

export interface StopServicesOptions {
  forcePorts?: boolean;
}

function getEnvFileArgs(dockerDir: string): string[] {
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
  /** Told where the raw compose output goes. */
  onLogFile?: (logPath: string) => void;
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
  const files = ["docker-compose.selfhost.yml"];
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

export function readStoredDevPid(repoPath: string): number | null {
  const pidPath = path.join(repoPath, DEV_PID_FILE);
  if (!fs.existsSync(pidPath)) return null;
  try {
    const pid = Number.parseInt(fs.readFileSync(pidPath, "utf-8").trim(), 10);
    return Number.isNaN(pid) || pid <= 0 ? null : pid;
  } catch {
    return null;
  }
}

export function isPidAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    return code === "EPERM";
  }
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

  const dockerComposePath = path.join(repoPath, "infra/docker");
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
  const pullSize = options?.build
    ? undefined
    : await measurePull(dockerComposePath, composeArgs, dockerEnv, {
        always: options?.pull === "always",
      });
  const result = await runCompose(
    buildSelfhostUpArgs(files, envArgs, options),
    {
      cwd: dockerComposePath,
      env: dockerEnv,
      timeoutMs: resolveStartTimeoutMs(),
      logName: options?.build ? "compose-build" : "compose-up",
      rebuildCommand: options?.rebuildCommand ?? REBUILD_COMMAND,
      onLogFile: options?.onLogFile,
      onProgress,
      pullSize,
    },
  ).catch(async (error: unknown) => {
    throw await withServiceLogTail(error, composeArgs, dockerComposePath);
  });
  if (await dockerVolumeExists(LEGACY_SANDBOX_VOLUME)) {
    onStatus?.("Moving code-sandbox files into per-user workspaces…");
    await runCommand(
      "docker",
      legacySandboxMigrationArgs(files, envArgs),
      dockerComposePath,
      undefined,
      undefined,
      dockerEnv,
    );
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
  const dockerComposePath = path.join(repoPath, "infra/docker");
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
    dockerComposePath,
    undefined,
    onLog,
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
  const dockerComposePath = path.join(repoPath, "infra/docker");
  const composeArgs = [
    ...composeFileArgs(selfhostComposeFiles()),
    ...getEnvFileArgs(dockerComposePath),
  ];
  const services = [
    ...SELFHOST_APP_SERVICES,
    ...(readConfig()?.bots ?? []).map(botService),
  ];
  // The shell environment outranks infra/docker/.env in compose interpolation.
  const env = { GAIA_VERSION: version };
  await runCompose([...composeArgs, "pull", ...services], {
    cwd: dockerComposePath,
    env,
    logName: "compose-pull",
    rebuildCommand: "gaia up --build",
    onProgress,
    pullSize: await measurePull(dockerComposePath, composeArgs, env, {
      services,
      always: true,
    }),
  });
}

export async function stopServices(
  repoPath: string,
  onStatus?: (status: string) => void,
  portOverrides?: Record<number, number>,
  options?: StopServicesOptions,
): Promise<void> {
  const dockerComposePath = path.join(repoPath, "infra/docker");
  const mode = await detectSetupMode(repoPath);

  const access = await getDockerAccess();
  if (access === "ready") {
    onStatus?.("Stopping GAIA's containers…");
    const envArgs = getEnvFileArgs(dockerComposePath);
    const fileArgs =
      mode === "selfhost" ? composeFileArgs(selfhostComposeFiles()) : [];
    await runCompose([...fileArgs, ...envArgs, "down"], {
      cwd: dockerComposePath,
      logName: "compose-down",
      rebuildCommand: REBUILD_COMMAND,
      onProgress: (phase) => onStatus?.(phase.label),
    });
  } else if (mode === "selfhost") {
    // Self-host runs only in Docker: "stopped" would be a lie.
    throw await dockerAccessError(access);
  } else if (access === "no-permission") {
    throw await dockerAccessError(access);
  }

  // In selfhost mode everything runs in Docker, no local processes to kill
  if (mode !== "selfhost") {
    await stopDeveloperProcesses(repoPath, onStatus, portOverrides, options);
  }
  onStatus?.("All services stopped.");
}

/** Stop `gaia dev`'s local processes: by its stored PID, or by port with --force-ports. */
async function stopDeveloperProcesses(
  repoPath: string,
  onStatus?: (status: string) => void,
  portOverrides?: Record<number, number>,
  options?: StopServicesOptions,
): Promise<void> {
  onStatus?.("Stopping GAIA-managed local processes (safe mode)…");
  const pid = readStoredDevPid(repoPath);
  const killedByPid = pid !== null && (await killDevProcess(repoPath, pid));
  try {
    fs.unlinkSync(path.join(repoPath, DEV_PID_FILE));
  } catch {
    // The PID file may never have existed.
  }
  if (killedByPid) return;

  // Fall back to port-based cleanup only when explicitly requested.
  if (options?.forcePorts) {
    onStatus?.("No GAIA PID found. Force-stopping listeners on app ports…");
    await killPortListeners(repoPath, [
      portOverrides?.[8000] ?? 8000,
      portOverrides?.[3000] ?? 3000,
    ]);
    return;
  }
  onStatus?.(
    pid !== null
      ? "Stored GAIA PID is stale. Skipping port cleanup in safe mode. Use `gaia stop --force-ports` for aggressive cleanup."
      : "No GAIA-managed PID found. Skipping port cleanup in safe mode. Use `gaia stop --force-ports` for aggressive cleanup.",
  );
}

/** Terminate a detached `gaia dev` session (its process group); false when it was not running. */
async function killDevProcess(repoPath: string, pid: number): Promise<boolean> {
  if (!isPidAlive(pid)) return false;
  try {
    if (process.platform === "win32") {
      await runCommand("taskkill", ["/PID", String(pid), "/T", "/F"], repoPath);
      return true;
    }
    signalGroup(pid, "SIGTERM");
    await delay(800);
    if (isPidAlive(pid)) signalGroup(pid, "SIGKILL");
    return true;
  } catch {
    // The process exited between the check and the signal.
    return false;
  }
}

/** Signal a process group, or the lone process when it leads no group. */
function signalGroup(pid: number, signal: NodeJS.Signals): void {
  try {
    process.kill(-pid, signal);
  } catch {
    process.kill(pid, signal);
  }
}

/** Kill whatever listens on each port (--force-ports; may hit non-GAIA processes). */
async function killPortListeners(
  repoPath: string,
  ports: number[],
): Promise<void> {
  for (const port of ports) {
    const [cmd, args] =
      process.platform === "win32"
        ? [
            "powershell",
            [
              "-Command",
              `Get-NetTCPConnection -LocalPort ${port} -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }`,
            ],
          ]
        : [
            "sh",
            [
              "-c",
              `lsof -ti :${port} -sTCP:LISTEN | xargs kill 2>/dev/null || true`,
            ],
          ];
    await runCommand(cmd, args, repoPath);
  }
}

export async function detectSetupMode(
  repoPath: string,
): Promise<SetupMode | null> {
  const envPath = apiEnvPath(repoPath);
  if (!fs.existsSync(envPath)) return null;

  const content = fs.readFileSync(envPath, "utf-8");

  // First, check for explicit SETUP_MODE marker (most robust)
  const setupModeMatch = content.match(/^SETUP_MODE=(.+)$/m);
  if (setupModeMatch?.[1]) {
    const mode = setupModeMatch[1].trim().replace(/^["']|["']$/g, "");
    if (mode === "selfhost" || mode === "developer") {
      return mode;
    }
  }

  if (content.includes("mongodb://mongo:"))
    // Fallback: string matching for backward compatibility
    return "selfhost";
  if (content.includes("mongodb://localhost:")) return "developer";

  return "developer";
}

/** Whole lines of a failed command's output an error quotes; never a cut mid-word. */
const ERROR_TAIL_LINES = 8;

function lastLines(output: string, count: number): string {
  return output.trimEnd().split("\n").slice(-count).join("\n");
}

export async function runCommand(
  cmd: string,
  args: string[],
  cwd: string,
  onProgress?: (progress: number) => void,
  onLog?: (chunk: string) => void,
  env?: Record<string, string>,
  timeoutMs?: number,
): Promise<void> {
  const { spawn } = await import("child_process");

  return new Promise((resolve, reject) => {
    const proc = spawn(cmd, args, {
      cwd,
      stdio: ["ignore", "pipe", "pipe"],
      env: env ? { ...process.env, ...env } : undefined,
    });

    let output = "";
    let progress = 0;
    let timedOut = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    if (timeoutMs) {
      timer = setTimeout(() => {
        timedOut = true;
        proc.kill("SIGTERM");
        reject(
          new Error(
            `Command timed out after ${Math.round(timeoutMs / 60000)}m. Check \`docker compose logs\` to debug.`,
          ),
        );
      }, timeoutMs);
    }

    proc.stdout?.on("data", (data) => {
      const chunk = data.toString();
      output += chunk;
      onLog?.(chunk);
      progress = Math.min(progress + 5, 95);
      onProgress?.(progress);
    });

    proc.stderr?.on("data", (data) => {
      const chunk = data.toString();
      output += chunk;
      onLog?.(chunk);
      progress = Math.min(progress + 5, 95);
      onProgress?.(progress);
    });

    proc.on("close", (code) => {
      if (timer) clearTimeout(timer);
      if (timedOut) return;
      if (code === 0) {
        onProgress?.(100);
        resolve();
      } else {
        reject(
          new Error(
            `Command failed with code ${code}:\n${lastLines(output, ERROR_TAIL_LINES)}`,
          ),
        );
      }
    });

    proc.on("error", (err) => {
      if (timer) clearTimeout(timer);
      if (timedOut) return;
      reject(err);
    });
  });
}

/** The file whose presence marks a directory as a GAIA checkout. */
const CHECKOUT_MARKER = "apps/api/app/config/settings_validator.py";

/** The API env file `gaia up` / `gaia setup` write; a checkout without it is unconfigured. */
export function apiEnvPath(repoPath: string): string {
  return path.join(repoPath, "apps", "api", ".env");
}

/** A source checkout: what the developer commands (init, setup, dev) need. */
export function isGaiaCheckout(dir: string): boolean {
  return fs.existsSync(path.join(dir, CHECKOUT_MARKER));
}

/** @throws Error when the install holds only a release's setup files, which cannot be built. */
export function assertBuildableInstall(repoPath: string): void {
  if (isGaiaCheckout(repoPath)) return;
  throw new Error(
    `Building GAIA needs its source, and ${homeRelative(repoPath)} holds only a release's setup files.\n` +
      "Get the source with 'gaia init', then build there.",
  );
}

/** A self-host install: a release's setup files (the bundle) or a source checkout. */
export function isGaiaInstall(dir: string): boolean {
  return fs.existsSync(path.join(dir, BUNDLE_MANIFEST)) || isGaiaCheckout(dir);
}

/** The nearest directory at or above startDir that matches. */
function findAbove(
  startDir: string,
  matches: (dir: string) => boolean,
): string | null {
  let currentDir = startDir;
  while (currentDir !== path.dirname(currentDir)) {
    if (matches(currentDir)) return currentDir;
    currentDir = path.dirname(currentDir);
  }
  return null;
}

/** The install recorded in ~/.gaia/config.json; a record that names no install is reset. */
function findRecordedInstall(): string | null {
  const config = readConfig();
  if (!config?.repoPath) return null;
  if (isGaiaInstall(config.repoPath)) return config.repoPath;
  console.warn(
    `Warning: Saved repo path "${config.repoPath}" is no longer a valid GAIA installation. Resetting config.`,
  );
  updateConfig({ repoPath: "", setupComplete: false });
  return null;
}

/** The source checkout to configure: the one at or above cwd, else the recorded install if it is one. */
export function findRepoRoot(startDir?: string): string | null {
  const local = findAbove(startDir ?? process.cwd(), isGaiaCheckout);
  if (local) return local;
  const recorded = findRecordedInstall();
  return recorded && isGaiaCheckout(recorded) ? recorded : null;
}

/**
 * The installation to inspect or run: a configured install at or above cwd,
 * else the recorded install. An unconfigured checkout (a source clone) never
 * shadows the install `gaia up` recorded.
 */
export function findInstallRoot(startDir?: string): string | null {
  const local = findAbove(startDir ?? process.cwd(), isGaiaInstall);
  if (local && fs.existsSync(apiEnvPath(local))) return local;
  return findRecordedInstall() ?? local;
}

/** "path (mode)": which installation a command is inspecting. */
export function describeInstall(
  repoPath: string | null,
  mode: SetupMode | null,
): string {
  if (!repoPath) return "GAIA isn't installed yet";
  const shown = homeRelative(repoPath);
  if (!mode) return `${shown} (not set up yet: no apps/api/.env)`;
  return `${shown} (${mode === "selfhost" ? "self-host" : "developer"})`;
}

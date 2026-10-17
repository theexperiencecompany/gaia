import * as fs from "fs";
import * as path from "path";
import { botComposeFile, botService, writeBotsEnv } from "./bots.js";
import { readConfig, updateConfig } from "./config.js";
import {
  assertEngineSupportsCodeSandbox,
  dockerVolumeExists,
} from "./docker.js";
import { dockerAccessError, getDockerAccess } from "./docker-access.js";
import type { SetupMode } from "./env-parser.js";
import { portOverridesToDockerEnv } from "./env-writer.js";

const delay = (ms: number): Promise<void> =>
  new Promise((r) => setTimeout(r, ms));

export const DEV_LOG_FILE = "dev-start.log";
export const DEV_PID_FILE = ".gaia-dev.pid";

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
}

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

/** Build the `docker compose ... up` argument list for self-host mode. */
function buildSelfhostUpArgs(
  files: string[],
  envArgs: string[],
  options?: StartServicesOptions,
): string[] {
  const upArgs = [
    "compose",
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

/** A GAIA image ref in compose's missing-image errors ("No such image", "failed to resolve reference"). */
const MISSING_GAIA_IMAGE =
  /(?:No such image: |failed to resolve reference ")(ghcr\.io\/theexperiencecompany\/gaia[\w-]*:([\w.-]+))/;

/** A `gaia up`/`start` hit a GAIA release whose images were never published. */
export class UnpublishedImageError extends Error {
  constructor(imageRef: string, version: string, options?: ErrorOptions) {
    super(
      `GAIA ${version} images aren't published (${imageRef}). Run \`gaia update\`, or \`gaia up --build\` to build from source.`,
      options,
    );
    this.name = "UnpublishedImageError";
  }
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
  onLog?: (chunk: string) => void,
  options?: StartServicesOptions,
): Promise<void> {
  if (setupMode !== "selfhost") {
    onStatus?.("Developer mode must run in foreground.");
    throw new Error(
      "Developer mode runs in foreground. Use 'gaia dev' or 'gaia dev full' instead of 'gaia start'.",
    );
  }

  onStatus?.(
    options?.build
      ? "Building and starting all services in Docker..."
      : "Starting all services in Docker (selfhost mode)...",
  );

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
  const envArgs = getEnvFileArgs(dockerComposePath);

  try {
    await runCommand(
      "docker",
      buildSelfhostUpArgs(files, envArgs, options),
      dockerComposePath,
      undefined,
      onLog,
      dockerEnv,
      resolveStartTimeoutMs(),
    );
  } catch (error) {
    const missing = MISSING_GAIA_IMAGE.exec((error as Error).message);
    if (missing?.[1] && missing[2]) {
      throw new UnpublishedImageError(missing[1], missing[2], { cause: error });
    }
    throw error;
  }
  if (await dockerVolumeExists(LEGACY_SANDBOX_VOLUME)) {
    onStatus?.("Moving code-sandbox files into per-user workspaces...");
    await runCommand(
      "docker",
      legacySandboxMigrationArgs(files, envArgs),
      dockerComposePath,
      undefined,
      onLog,
      dockerEnv,
    );
  }
  onStatus?.("All services started in Docker!");
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
): Promise<void> {
  const dockerComposePath = path.join(repoPath, "infra/docker");
  await runCommand(
    "docker",
    [
      "compose",
      ...composeFileArgs(selfhostComposeFiles()),
      ...getEnvFileArgs(dockerComposePath),
      "pull",
      ...SELFHOST_APP_SERVICES,
      ...(readConfig()?.bots ?? []).map(botService),
    ],
    dockerComposePath,
    undefined,
    undefined,
    // The shell environment outranks infra/docker/.env in compose interpolation.
    { GAIA_VERSION: version },
  );
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
    onStatus?.("Stopping GAIA's containers...");
    const envArgs = getEnvFileArgs(dockerComposePath);
    const composeArgs =
      mode === "selfhost"
        ? [
            "compose",
            ...composeFileArgs(selfhostComposeFiles()),
            ...envArgs,
            "down",
          ]
        : ["compose", ...envArgs, "down"];
    await runCommand("docker", composeArgs, dockerComposePath);
  } else if (mode === "selfhost") {
    // Self-host runs only in Docker: "stopped" would be a lie.
    throw await dockerAccessError(access);
  } else if (access === "no-permission") {
    throw await dockerAccessError(access);
  }

  // In selfhost mode everything runs in Docker, no local processes to kill
  if (mode !== "selfhost") {
    onStatus?.("Stopping GAIA-managed local processes (safe mode)...");
    const pidPath = path.join(repoPath, DEV_PID_FILE);
    let killedByPid = false;

    // Try to kill by stored PID first (targets only GAIA processes).
    const pid = readStoredDevPid(repoPath);
    const hadStoredPid = typeof pid === "number";
    if (pid && isPidAlive(pid)) {
      try {
        if (process.platform === "win32") {
          await runCommand(
            "taskkill",
            ["/PID", String(pid), "/T", "/F"],
            repoPath,
          );
          killedByPid = true;
        } else {
          // Prefer process-group termination for detached `gaia dev` sessions.
          try {
            process.kill(-pid, "SIGTERM");
            killedByPid = true;
          } catch {
            // Fallback to direct PID if group kill is unavailable.
            process.kill(pid, "SIGTERM");
            killedByPid = true;
          }
          await delay(800);
          if (isPidAlive(pid)) {
            try {
              process.kill(-pid, "SIGKILL");
            } catch {
              process.kill(pid, "SIGKILL");
            }
          }
        }
      } catch {
        // Ignore PID termination errors
      }
    }

    try {
      fs.unlinkSync(pidPath);
    } catch {
      // Ignore cleanup errors
    }

    // Fall back to port-based cleanup only when explicitly requested.
    if (!killedByPid && options?.forcePorts) {
      onStatus?.("No GAIA PID found. Force-stopping listeners on app ports...");
      try {
        const apiPort = portOverrides?.[8000] ?? 8000;
        const webPort = portOverrides?.[3000] ?? 3000;

        if (process.platform === "win32") {
          for (const port of [apiPort, webPort]) {
            try {
              await runCommand(
                "powershell",
                [
                  "-Command",
                  `Get-NetTCPConnection -LocalPort ${port} -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }`,
                ],
                repoPath,
              );
            } catch {
              // Port not in use
            }
          }
        } else {
          for (const port of [apiPort, webPort]) {
            try {
              await runCommand(
                "sh",
                [
                  "-c",
                  `lsof -ti :${port} -sTCP:LISTEN | xargs kill 2>/dev/null || true`,
                ],
                repoPath,
              );
            } catch {
              // Port not in use
            }
          }
        }
      } catch {
        // Ignore cleanup errors
      }
    } else if (!killedByPid) {
      onStatus?.(
        hadStoredPid
          ? "Stored GAIA PID is stale. Skipping port cleanup in safe mode. Use `gaia stop --force-ports` for aggressive cleanup."
          : "No GAIA-managed PID found. Skipping port cleanup in safe mode. Use `gaia stop --force-ports` for aggressive cleanup.",
      );
    }
  }

  onStatus?.("All services stopped.");
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
          new Error(`Command failed with code ${code}: ${output.slice(-500)}`),
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

export function isGaiaCheckout(dir: string): boolean {
  return fs.existsSync(path.join(dir, CHECKOUT_MARKER));
}

/** The nearest GAIA checkout at or above startDir. */
function findCheckoutAbove(startDir: string): string | null {
  let currentDir = startDir;
  while (currentDir !== path.dirname(currentDir)) {
    if (isGaiaCheckout(currentDir)) return currentDir;
    currentDir = path.dirname(currentDir);
  }
  return null;
}

/** The install recorded in ~/.gaia/config.json; a stale record is reset. */
function findRecordedCheckout(): string | null {
  const config = readConfig();
  if (!config?.repoPath) return null;
  if (isGaiaCheckout(config.repoPath)) return config.repoPath;
  console.warn(
    `Warning: Saved repo path "${config.repoPath}" is no longer a valid GAIA installation. Resetting config.`,
  );
  updateConfig({ repoPath: "", setupComplete: false });
  return null;
}

/** The checkout to configure: the one at or above cwd, else the recorded install. */
export function findRepoRoot(startDir?: string): string | null {
  return findCheckoutAbove(startDir ?? process.cwd()) ?? findRecordedCheckout();
}

/**
 * The installation to inspect or run: a configured checkout at or above cwd,
 * else the recorded install. An unconfigured checkout (a source clone) never
 * shadows the install `gaia up` recorded.
 */
export function findInstallRoot(startDir?: string): string | null {
  const local = findCheckoutAbove(startDir ?? process.cwd());
  if (local && fs.existsSync(apiEnvPath(local))) return local;
  return findRecordedCheckout() ?? local;
}

/** "path (mode)": which installation a command is inspecting. */
export function describeInstall(
  repoPath: string | null,
  mode: SetupMode | null,
): string {
  if (!repoPath) return "GAIA isn't installed yet";
  if (!mode) return `${repoPath} (not set up yet: no apps/api/.env)`;
  return `${repoPath} (${mode === "selfhost" ? "self-host" : "developer"})`;
}

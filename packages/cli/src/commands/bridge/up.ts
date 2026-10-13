// `gaia bridge up` — register configured servers with the cloud, then hold the
// tunnel as a detached background daemon (stop it with `gaia bridge down`).

import {
  type ChildProcess,
  type SpawnOptions,
  spawn,
} from "node:child_process";
import {
  existsSync,
  mkdirSync,
  openSync,
  readFileSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { registerConfiguredServers } from "@gaia/shared/bridge-core/register";
import { ApiError } from "./api.js";
import { clearCredentials, loadConfig, loadCredentials } from "./config.js";
import { runLogin } from "./login.js";
import { Tunnel } from "./tunnel.js";

const DAEMON_DIR = join(homedir(), ".gaia", "bridge");
const PID_FILE = join(DAEMON_DIR, "daemon.pid");
const LOG_FILE = join(DAEMON_DIR, "daemon.log");

/** The pid of a live background tunnel, or null. Clears a stale pidfile whose
 * process is gone so a fresh `up` can start. */
function runningDaemonPid(): number | null {
  if (!existsSync(PID_FILE)) return null;
  const pid = Number(readFileSync(PID_FILE, "utf-8").trim());
  if (!pid) return null;
  try {
    process.kill(pid, 0); // signal 0 probes liveness without killing
    return pid;
  } catch {
    return null; // process is gone; treat the pidfile as stale
  }
}

/** One line for `gaia bridge ls`. */
export function daemonStatusLine(): string {
  const pid = runningDaemonPid();
  return pid
    ? `Tunnel: running in the background (pid ${pid}) — stop with: gaia bridge down`
    : "Tunnel: not running — start with: gaia bridge up";
}

/** `gaia bridge down` — stop the background tunnel. */
export function stopDaemon(): void {
  const pid = runningDaemonPid();
  if (!pid) {
    if (existsSync(PID_FILE)) unlinkSync(PID_FILE);
    console.info("No bridge tunnel is running.");
    return;
  }
  try {
    process.kill(pid, "SIGTERM");
  } catch {
    // vanished between the probe and the signal — nothing left to stop
  }
  if (existsSync(PID_FILE)) unlinkSync(PID_FILE);
  console.info(`Stopped the bridge tunnel (pid ${pid}).`);
}

export async function runUp(): Promise<void> {
  // Never start a second daemon: two tunnels on one machine rotate the same
  // refresh token and trip reuse-detection, which revokes the device.
  const existing = runningDaemonPid();
  if (existing) {
    console.info(
      `Bridge tunnel is already running (pid ${existing}) — it already serves your configured servers, including any you just added. Nothing else to do.`,
    );
    return;
  }

  // While the tunnel is up, GAIA can run commands and read/write files on this
  // machine via run_on_device — full access, nothing to configure.
  console.error(
    "[gaia bridge] connected: GAIA can run commands and access files on this machine.",
  );

  const urlWithHeaders = loadConfig().servers.filter(
    (s) => s.type === "url" && s.headers && Object.keys(s.headers).length > 0,
  );
  if (urlWithHeaders.length > 0) {
    console.error(
      `[gaia bridge] forwarding request headers (credentials) to ${urlWithHeaders.length} local url server(s).`,
    );
  }

  // Register in the FOREGROUND so pairing/self-heal can prompt interactively —
  // the detached daemon has no terminal to ask on. A revoked or unpaired device
  // fails the first token exchange (401); drop the dead credentials and re-pair.
  try {
    await registerConfiguredServers();
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      console.error(
        "[gaia bridge] this device is no longer authorized (revoked or unpaired). Let's re-pair.\n",
      );
      clearCredentials();
      await runLogin();
      await registerConfiguredServers();
    } else {
      throw e;
    }
  }

  // Hand the tunnel to a detached child so the user's terminal is free. The
  // child re-runs this CLI with the internal `--serve` flag and logs to a file.
  const entry = process.argv[1];
  if (!entry) {
    throw new Error(
      "cannot locate the gaia CLI entrypoint to start the daemon",
    );
  }
  mkdirSync(DAEMON_DIR, { recursive: true, mode: 0o700 });
  const log = openSync(LOG_FILE, "a");
  const spawnOpts: SpawnOptions = {
    detached: true,
    stdio: ["ignore", log, log],
  };
  // Forward execArgv so a tsx-dev run (`node --import tsx …`) re-execs the child
  // with the same loader; production (`node dist/index.js`) has empty execArgv.
  const child: ChildProcess = spawn(
    process.execPath,
    [...process.execArgv, entry, "bridge", "up", "--serve"],
    spawnOpts,
  );
  child.unref();
  writeFileSync(PID_FILE, String(child.pid ?? ""), { mode: 0o600 });
  console.info(
    `\nBridge tunnel started in the background (pid ${child.pid}).\n` +
      `  Logs:  ${LOG_FILE}\n` +
      `  Stop:  gaia bridge down`,
  );
}

/** The detached worker: hold the tunnel until killed. Users never call this
 * directly — `runUp` spawns it via `gaia bridge up --serve`. */
export async function runServe(): Promise<void> {
  const creds = loadCredentials();
  if (!creds?.refreshToken)
    throw new Error("not paired — run: gaia bridge login");

  const tunnel = new Tunnel(creds);
  const shutdown = async () => {
    await tunnel.stop();
    process.exit(0);
  };
  process.on("SIGINT", () => void shutdown());
  process.on("SIGTERM", () => void shutdown());
  await tunnel.run();
}

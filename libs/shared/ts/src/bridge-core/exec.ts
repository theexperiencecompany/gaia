// `run_on_device` daemon side — the cloud sends a shell command, we run it as
// the user and stream stdout/stderr/exit back over the tunnel.
//
// There is intentionally NO local gate: pairing this device and starting the
// bridge IS the grant (the owner opted in physically). The command runs in the
// user's own shell, so shell metacharacters are expected, not sanitized — the
// trust boundary is the pairing, not the command text. We only bound blast:
// a wall-clock timeout, a combined-output cap, and an append-only audit log.

import { spawn } from "node:child_process";
import { appendFileSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import {
  DEVICE_EXEC_MAX_OUTPUT_BYTES,
  DEVICE_EXEC_TIMEOUT_MS,
} from "./constants.js";
import { bridgeEnv } from "./env.js";

export interface ExecFrames {
  stdout: (data: string) => void;
  stderr: (data: string) => void;
  exit: (code: number) => void;
}

function audit(command: string, cwd: string | undefined): void {
  try {
    const dir = bridgeEnv().stateDir;
    mkdirSync(dir, { recursive: true, mode: 0o700 });
    const where = cwd ? ` (cwd: ${cwd})` : "";
    appendFileSync(
      join(dir, "exec-audit.log"),
      `${new Date().toISOString()}${where} $ ${command}\n`,
    );
  } catch {
    // Auditing is best-effort; a log-write failure must not block the command.
  }
}

/** Run `command` under the user's shell, streaming output through `frames`.
 * Resolves once the process exits (or is killed by the timeout / output cap). */
export async function runDeviceExec(
  command: string,
  cwd: string | undefined,
  frames: ExecFrames,
): Promise<void> {
  audit(command, cwd);

  const child = spawn(bridgeEnv().shell, ["-c", command], {
    // Default to the user's home, not the (arbitrary) directory the daemon was
    // launched from — a predictable base for `~`-relative and bare paths.
    cwd: cwd || homedir(),
    env: bridgeEnv().env,
    // stdin is /dev/null: the agent cannot type, so an interactive command
    // (a wizard, a REPL, `read`) must get EOF and move on rather than block
    // until the timeout. stdout/stderr stay pipes so we can stream them.
    stdio: ["ignore", "pipe", "pipe"],
  });

  let sent = 0;
  let capped = false;

  const forward = (kind: "stdout" | "stderr") => (chunk: Buffer) => {
    if (capped) return;
    const remaining = DEVICE_EXEC_MAX_OUTPUT_BYTES - sent;
    const slice =
      chunk.length > remaining ? chunk.subarray(0, remaining) : chunk;
    if (slice.length > 0) {
      sent += slice.length;
      frames[kind](slice.toString("utf-8"));
    }
    if (sent >= DEVICE_EXEC_MAX_OUTPUT_BYTES) {
      capped = true;
      frames.stderr("\n[gaia bridge] output truncated — cap reached\n");
      child.kill("SIGKILL");
    }
  };
  child.stdout.on("data", forward("stdout"));
  child.stderr.on("data", forward("stderr"));

  const timer = setTimeout(() => {
    frames.stderr(
      `\n[gaia bridge] killed — exceeded ${DEVICE_EXEC_TIMEOUT_MS / 1000}s timeout\n`,
    );
    child.kill("SIGKILL");
  }, DEVICE_EXEC_TIMEOUT_MS);

  await new Promise<void>((resolve) => {
    child.on("error", (err) => {
      clearTimeout(timer);
      frames.stderr(`[gaia bridge] could not start command: ${err.message}\n`);
      frames.exit(127);
      resolve();
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      frames.exit(code ?? -1);
      resolve();
    });
  });
}

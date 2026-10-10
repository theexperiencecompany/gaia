// A Finder/login-launched macOS app inherits a minimal PATH (/usr/bin:/bin:…),
// so every npx/uvx/node the bridge spawns for run_on_device or a stdio MCP
// server fails ENOENT. Run the user's login shell once to capture the real
// interactive PATH and hand it to bridge-core. macOS only for now; on other
// platforms the process already launches with the login PATH intact.

import { spawn } from "node:child_process";

/** Bounded window for the login shell to print its PATH before we fall back. */
const LOGIN_SHELL_TIMEOUT_MS = 5_000;

/**
 * Resolve the user's real login-shell PATH.
 *
 * On darwin, spawns `$SHELL -ilc 'printf %s "$PATH"'` (an interactive login
 * shell, so ~/.zprofile and ~/.zshrc run and PATH matches what the user sees in
 * Terminal), reads stdout, and falls back to the current process PATH on any
 * failure or if the shell does not answer within the timeout. On non-darwin it
 * returns the current process PATH unchanged.
 */
export async function resolveLoginShellPath(): Promise<string> {
  if (process.platform !== "darwin") {
    return process.env["PATH"] ?? "";
  }

  const shell = process.env["SHELL"] || "/bin/zsh";
  const fallbackPath = process.env["PATH"] ?? "";

  return new Promise<string>((resolvePath) => {
    let settled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const finish = (value: string): void => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      resolvePath(value);
    };

    let child: ReturnType<typeof spawn>;
    try {
      child = spawn(shell, ["-ilc", 'printf %s "$PATH"']);
    } catch {
      finish(fallbackPath);
      return;
    }

    timer = setTimeout(() => {
      child.kill("SIGKILL");
      finish(fallbackPath);
    }, LOGIN_SHELL_TIMEOUT_MS);

    let out = "";
    child.stdout?.on("data", (chunk: Buffer) => {
      out += chunk.toString();
    });
    child.on("error", () => finish(fallbackPath));
    child.on("close", (code) => {
      const resolved = out.trim();
      finish(code === 0 && resolved ? resolved : fallbackPath);
    });
  });
}

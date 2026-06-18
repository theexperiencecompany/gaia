/**
 * App/URL launching and window listing for the desktop tool bridge.
 *
 * @module tools/apps
 */

import { execFile } from "node:child_process";
import { promisify } from "node:util";
import type { DesktopWindowInfo } from "@gaia/shared/desktop-tools";
import { shell } from "electron";

const execFileAsync = promisify(execFile);

const OPEN_APP_TIMEOUT_MS = 10_000;
const LIST_WINDOWS_TIMEOUT_MS = 10_000;

/** AppleScript: visible processes with their window titles, tab-separated. */
const LIST_WINDOWS_SCRIPT = `
tell application "System Events"
  set out to ""
  repeat with proc in (application processes whose visible is true)
    set procName to name of proc
    repeat with w in (windows of proc)
      set out to out & procName & tab & (name of w) & linefeed
    end repeat
  end repeat
  return out
end tell`;

export async function openApp(appName: string): Promise<void> {
  const trimmed = appName.trim();
  if (!trimmed) {
    throw new Error("App name is empty");
  }
  if (process.platform !== "darwin") {
    throw new Error("Opening apps is only supported on macOS for now");
  }
  // No app allowlist by design: which app to launch is a model decision,
  // gated upstream to the authenticated user's DESKTOP-source stream — the
  // model + that gating is the trust boundary, not this layer. Safety here is
  // execFile (no shell) with an absolute path to the SIP-protected system
  // binary: the app name is a literal argv entry, never via $PATH or a shell,
  // so it cannot inject commands regardless of its contents.
  await execFileAsync("/usr/bin/open", ["-a", trimmed], {
    timeout: OPEN_APP_TIMEOUT_MS,
  });
}

export async function openUrl(url: string): Promise<void> {
  if (!url.startsWith("https://") && !url.startsWith("http://")) {
    throw new Error("Only http(s) URLs can be opened");
  }
  await shell.openExternal(url);
}

export async function listWindows(): Promise<{
  windows: DesktopWindowInfo[];
}> {
  if (process.platform !== "darwin") {
    throw new Error("Listing windows is only supported on macOS for now");
  }
  // Requires the Automation (System Events) permission; macOS prompts on
  // first use. A denial surfaces here as a non-zero osascript exit.
  const { stdout } = await execFileAsync(
    "/usr/bin/osascript",
    ["-e", LIST_WINDOWS_SCRIPT],
    { timeout: LIST_WINDOWS_TIMEOUT_MS },
  );

  const windows: DesktopWindowInfo[] = [];
  for (const line of stdout.split("\n")) {
    const [app, ...titleParts] = line.split("\t");
    if (!app?.trim()) continue;
    windows.push({ app: app.trim(), title: titleParts.join("\t").trim() });
  }
  return { windows };
}

import * as fs from "fs";
import * as path from "path";
import { runInteractiveCommand } from "../../lib/interactive.js";
import {
  DEV_PID_FILE,
  detectSetupMode,
  findRepoRoot,
} from "../../lib/service-starter.js";

export async function runDev(profile?: string): Promise<void> {
  if (profile && profile !== "full") {
    throw new Error(
      `Invalid developer profile: '${profile}'. Use 'gaia dev' or 'gaia dev full'.`,
    );
  }

  const repoPath = findRepoRoot();
  if (!repoPath) {
    throw new Error(
      "Could not find GAIA repository. Run from within a cloned gaia repo.",
    );
  }

  const setupMode = await detectSetupMode(repoPath);
  if (!setupMode) {
    throw new Error(
      "No .env file found. Run 'gaia init' for fresh setup, or 'gaia setup' to configure an existing repo.",
    );
  }

  if (setupMode !== "developer") {
    throw new Error(
      "Developer mode is not enabled for this repo. Use 'gaia start' for self-host mode.",
    );
  }

  const pidPath = path.join(repoPath, DEV_PID_FILE);
  try {
    await runInteractiveCommand(
      "mise",
      [profile === "full" ? "dev:full" : "dev"],
      repoPath,
      undefined,
      (pid) => {
        if (typeof pid === "number" && pid > 0) {
          fs.writeFileSync(pidPath, `${pid}\n`);
        }
      },
      process.platform !== "win32",
    );
  } finally {
    try {
      fs.unlinkSync(pidPath);
    } catch {
      // PID file may already be absent
    }
  }
}

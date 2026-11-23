// CLI wrapper for the device pairing flow. bridge-core's runLogin does the work;
// this supplies the console-backed listener (today's exact pairing output) and
// the CLI version. `isPaired` is re-exported unchanged.

import { DEFAULT_API_URL } from "@gaia/shared/bridge-core/constants";
import {
  isPaired,
  type LoginListener,
  runLogin as runLoginCore,
} from "@gaia/shared/bridge-core/login";
import { detectSetupMode, findInstallRoot } from "../../lib/install-root.js";
import { isInteractive } from "../../lib/non-tty.js";
import {
  notServingHelp,
  notServingPrompt,
  selfhostPairing,
} from "../../lib/pairing-origin.js";
import { confirm } from "../../lib/prompt.js";
import { CLI_VERSION } from "../../lib/version.js";

export { isPaired };

const consoleListener: LoginListener = {
  onPrompt(verificationUrl, userCode) {
    console.info("\nTo pair this device, open:\n");
    console.info(`  ${verificationUrl}`);
    console.info(`\nand enter this code:  ${userCode}\n`);
  },
  onStatus(status) {
    console.info(status);
  },
};

/**
 * The API to pair with: this machine's self-host install when it answers, else
 * GAIA Cloud once the user agrees. A dead install never redirects silently —
 * pairing decides which GAIA reaches this machine's files and MCP servers.
 */
async function resolveApi(): Promise<string | undefined> {
  const repoPath = findInstallRoot();
  if (!repoPath || (await detectSetupMode(repoPath)) !== "selfhost") {
    return undefined;
  }

  const pairing = await selfhostPairing(repoPath);
  if (pairing.kind === "serving") return pairing.origin;

  if (isInteractive() && (await confirm(notServingPrompt(pairing)))) {
    return DEFAULT_API_URL;
  }
  throw new Error(notServingHelp(pairing));
}

/** Pairs with --api, else GAIA_API_URL, else this machine's self-host install, else GAIA Cloud. */
export async function runLogin(
  options: { api?: string; name?: string } = {},
): Promise<void> {
  const api =
    options.api ??
    (process.env["GAIA_API_URL"] ? undefined : await resolveApi());
  await runLoginCore(consoleListener, {
    ...options,
    ...(api !== undefined ? { api } : {}),
    daemonVersion: CLI_VERSION,
  });
}

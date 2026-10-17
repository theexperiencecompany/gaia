// CLI wrapper for the device pairing flow. bridge-core's runLogin does the work;
// this supplies the console-backed listener (today's exact pairing output) and
// the CLI version. `isPaired` is re-exported unchanged.

import {
  isPaired,
  type LoginListener,
  runLogin as runLoginCore,
} from "@gaia/shared/bridge-core/login";
import { localOrigin } from "../../lib/endpoints.js";
import { readDockerComposePortOverrides } from "../../lib/env-writer.js";
import { detectSetupMode, findInstallRoot } from "../../lib/service-starter.js";
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

/** Where this machine's self-host install answers, when it has one. */
async function selfhostInstallOrigin(): Promise<string | undefined> {
  const repoPath = findInstallRoot();
  if (!repoPath || (await detectSetupMode(repoPath)) !== "selfhost") {
    return undefined;
  }
  return localOrigin("selfhost", readDockerComposePortOverrides(repoPath));
}

/** Pairs with --api, else GAIA_API_URL, else this machine's self-host install, else GAIA Cloud. */
export async function runLogin(
  options: { api?: string; name?: string } = {},
): Promise<void> {
  const api =
    options.api ??
    (process.env["GAIA_API_URL"] ? undefined : await selfhostInstallOrigin());
  await runLoginCore(consoleListener, {
    ...options,
    ...(api !== undefined ? { api } : {}),
    daemonVersion: CLI_VERSION,
  });
}

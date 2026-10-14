// CLI wrapper for the device pairing flow. bridge-core's runLogin does the work;
// this supplies the console-backed listener (today's exact pairing output) and
// the CLI version. `isPaired` is re-exported unchanged.

import {
  isPaired,
  type LoginListener,
  runLogin as runLoginCore,
} from "@gaia/shared/bridge-core/login";
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

export async function runLogin(
  options: { api?: string; name?: string } = {},
): Promise<void> {
  await runLoginCore(consoleListener, {
    ...options,
    daemonVersion: CLI_VERSION,
  });
}

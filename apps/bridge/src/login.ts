// Device pairing flow, reusable by both `gaia bridge login` and the add wizard.

import { hostname, platform } from "node:os";
import { pollPairing, startPairing } from "./api.js";
import {
  apiUrlFromEnvOrCreds,
  loadCredentials,
  saveCredentials,
} from "./config.js";
import { VERSION } from "./version.js";

async function sleep(ms: number): Promise<void> {
  await new Promise((r) => setTimeout(r, ms));
}

export function isPaired(): boolean {
  return Boolean(loadCredentials()?.refreshToken);
}

export async function runLogin(
  options: { api?: string; name?: string } = {},
): Promise<void> {
  const apiUrl = apiUrlFromEnvOrCreds(options.api);
  const name = options.name || hostname();

  const started = await startPairing(apiUrl, name, platform(), VERSION);
  console.info("\nTo pair this device, open:\n");
  console.info(`  ${started.verification_url}`);
  console.info(`\nand enter this code:  ${started.user_code}\n`);
  console.info("Waiting for approval…");

  const deadline = Date.now() + started.expires_in * 1000;
  while (Date.now() < deadline) {
    await sleep(started.interval * 1000);
    const poll = await pollPairing(apiUrl, started.device_code);
    if (poll.status === "approved" && poll.device_id && poll.refresh_token) {
      saveCredentials({
        apiUrl,
        deviceId: poll.device_id,
        refreshToken: poll.refresh_token,
      });
      console.info(`\nPaired as "${name}".\n`);
      return;
    }
    if (poll.status === "denied" || poll.status === "expired") {
      throw new Error(`pairing ${poll.status}`);
    }
  }
  throw new Error("pairing timed out");
}

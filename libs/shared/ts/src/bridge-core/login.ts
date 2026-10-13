// Device pairing flow (RFC 8628 style), reusable by any host. The host supplies
// a LoginListener for the user-facing pairing UX (show the code, status) and its
// own daemon version; transient poll diagnostics go to the injected bridgeLogger,
// like every other bridge diagnostic.

import { hostname, platform } from "node:os";
import { type PollPairingResponse, pollPairing, startPairing } from "./api.js";
import {
  apiUrlFromEnvOrCreds,
  loadCredentials,
  saveCredentials,
} from "./config.js";
import { bridgeLogger } from "./env.js";

/** How a host renders the pairing flow to the user. `onPrompt` shows the
 * verification URL + code; `onStatus` reports progress ("waiting", "paired"). */
export interface LoginListener {
  onPrompt(verificationUrl: string, userCode: string): void;
  onStatus?(status: string): void;
}

async function sleep(ms: number): Promise<void> {
  await new Promise((r) => setTimeout(r, ms));
}

export function isPaired(): boolean {
  return Boolean(loadCredentials()?.refreshToken);
}

export async function runLogin(
  listener: LoginListener,
  options: { api?: string; name?: string; daemonVersion: string },
): Promise<void> {
  const apiUrl = apiUrlFromEnvOrCreds(options.api);
  const name = options.name || hostname();

  const started = await startPairing(
    apiUrl,
    name,
    platform(),
    options.daemonVersion,
  );
  listener.onPrompt(started.verification_url, started.user_code);
  listener.onStatus?.("Waiting for approval…");

  const deadline = Date.now() + started.expires_in * 1000;
  while (Date.now() < deadline) {
    await sleep(started.interval * 1000);
    let poll: PollPairingResponse;
    try {
      poll = await pollPairing(apiUrl, started.device_code);
    } catch (e) {
      // A transient network/HTTP blip mid-window must not abort pairing —
      // keep polling until the deadline. Only expired/timeout stop us.
      bridgeLogger().error(
        `[gaia bridge] poll failed, retrying: ${e instanceof Error ? e.message : e}`,
      );
      continue;
    }
    if (poll.status === "approved" && poll.device_id && poll.refresh_token) {
      saveCredentials({
        apiUrl,
        deviceId: poll.device_id,
        refreshToken: poll.refresh_token,
      });
      listener.onStatus?.(`\nPaired as "${name}".\n`);
      return;
    }
    if (poll.status === "expired") {
      throw new Error(`pairing ${poll.status}`);
    }
  }
  throw new Error("pairing timed out");
}

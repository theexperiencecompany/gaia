// Serialize refresh-token rotation across every process sharing one state dir.
//
// `gaia bridge up` (daemon reconnects) and one-shot commands (`add`, `rm`)
// each load the stored refresh token, exchange it at /device/token, and save
// the replacement. Two holders exchanging the same token concurrently land
// past the server's 60s retry grace as a replay — and a replay revokes the
// device. The in-memory reload before each exchange only helps within one
// process, so the load → exchange → save triple runs under this mutex.
//
// mkdir-based: atomic on POSIX and Windows, dependency-free, no fcntl. A
// holder killed mid-rotation leaves the dir behind, so the stamp inside ages
// it out (rotation holds the lock for one HTTPS round trip; anything older
// than STALE_MS is a dead holder, not a slow network).

import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { ApiError, exchangeToken } from "./api.js";
import { loadCredentials, saveCredentials } from "./config.js";
import type { Credentials } from "./config.types.js";
import { bridgeEnv } from "./env.js";

// Rotation holds the lock for one token exchange (~1s); a stamp older than
// this is a crashed holder. Generous on purpose — stealing a live holder's
// lock reintroduces the exact double-exchange this mutex exists to prevent.
const STALE_MS = 30_000;
// Give up waiting this long. The daemon's reconnect loop retries on error, so
// a timeout just defers one dial; one-shot commands surface it as a failure.
const ACQUIRE_TIMEOUT_MS = 30_000;
const POLL_MS = 50;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function lockDir(): string {
  return join(bridgeEnv().stateDir, "credentials.lock");
}

function stampPath(): string {
  return join(lockDir(), "stamp");
}

/** Run `fn` with the rotation mutex held. Reentrant within one process is a
 * programming error (rotation never nests) — it would deadlock, loudly. */
export async function withRotationLock<T>(fn: () => Promise<T>): Promise<T> {
  const dir = lockDir();
  const stamp = stampPath();
  // The parent may not exist on a fresh machine; creating it is idempotent,
  // so concurrent creators are harmless. The lock dir itself MUST stay a
  // plain (non-recursive) mkdir — that call is the atomic acquire.
  mkdirSync(dirname(dir), { recursive: true });
  const deadline = Date.now() + ACQUIRE_TIMEOUT_MS;
  for (;;) {
    try {
      mkdirSync(dir);
      break;
    } catch (e) {
      if ((e as NodeJS.ErrnoException)?.code !== "EEXIST") throw e;
    }
    // Someone holds it. A missing stamp means they acquired it an instant
    // ago and haven't written the stamp yet — wait, never steal.
    let ageMs: number | null = null;
    try {
      const written = Number(readFileSync(stamp, "utf-8"));
      ageMs = Number.isFinite(written)
        ? Date.now() - written
        : Number.POSITIVE_INFINITY;
    } catch (e) {
      if ((e as NodeJS.ErrnoException)?.code !== "ENOENT") {
        // Present but unreadable: a crashed holder's debris, not a live lock.
        ageMs = Number.POSITIVE_INFINITY;
      }
    }
    if (ageMs === null || ageMs < STALE_MS) {
      if (Date.now() > deadline) {
        throw new Error(
          "another gaia process is rotating the device credential — try again",
        );
      }
      await sleep(POLL_MS);
      continue;
    }
    // Stale: remove and loop back to mkdir (a concurrent stealer may win it).
    try {
      rmSync(dir, { recursive: true, force: true });
    } catch {
      // Lost the steal race; loop back and wait on the new holder.
    }
  }
  try {
    writeFileSync(stamp, String(Date.now()), { mode: 0o600 });
    return await fn();
  } finally {
    try {
      rmSync(dir, { recursive: true, force: true });
    } catch {
      // Best-effort release; a leftover dir ages out via the stamp.
    }
  }
}

/** The one locked credential-rotation path. Every exchange-then-save flows
 * through here — the daemon dial, foreground registration, and removal. */
export async function rotateCredentials(): Promise<{
  creds: Credentials;
  accessToken: string;
}> {
  return withRotationLock(async () => {
    // Re-read under the lock: another process may have rotated between our
    // read and acquiring the mutex.
    const stored = loadCredentials();
    if (!stored?.refreshToken) {
      throw new ApiError("not paired — run: gaia bridge login", 401);
    }
    const token = await exchangeToken(stored.apiUrl, stored.refreshToken);
    // Persist before returning: from here the old token is dead, and a crash
    // before saving strands us on it (the server's retry grace covers only a
    // lost *response*, not a lost write).
    const creds: Credentials = { ...stored, refreshToken: token.refresh_token };
    saveCredentials(creds);
    return { creds, accessToken: token.access_token };
  });
}

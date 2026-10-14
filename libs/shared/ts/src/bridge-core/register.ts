// Register every configured server with the cloud (creating its integration and
// enqueuing warm-connect). Split from serving so `gaia bridge add` can register a
// new server without starting a second tunnel.

import { deregisterServer, registerServer } from "./api.js";
import { loadConfig, removeServer } from "./config.js";
import { bridgeLogger } from "./env.js";
import { rotateCredentials } from "./rotation-lock.js";

export async function registerConfiguredServers(): Promise<void> {
  const servers = loadConfig().servers;
  if (servers.length === 0) {
    throw new Error("no servers configured — run: gaia bridge add");
  }
  const { creds, accessToken } = await rotateCredentials();
  // Independent registrations that all share the one already-exchanged access
  // token — register them concurrently rather than one round trip at a time.
  await Promise.all(
    servers.map((server) =>
      registerServer(
        creds.apiUrl,
        accessToken,
        server.key,
        server.name,
        server.type,
      ),
    ),
  );
}

// Remove one server: drop it from local config first (durable regardless of
// network), then best-effort tell the cloud to prune its rows. If the cloud call
// fails, the HELLO reconcile on the next connect is the backstop.
export async function deregisterConfiguredServer(
  key: string,
): Promise<boolean> {
  const removed = removeServer(key);
  try {
    const { creds, accessToken } = await rotateCredentials();
    await deregisterServer(creds.apiUrl, accessToken, key);
  } catch (err) {
    bridgeLogger().info(
      `[gaia bridge] removed '${key}' locally; the cloud will reconcile on next connect (${err instanceof Error ? err.message : String(err)})`,
    );
  }
  return removed;
}

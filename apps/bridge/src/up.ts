// `gaia bridge up` — register configured servers with the cloud and hold the tunnel.

import { exchangeToken, registerServer } from "./api.js";
import {
  getFilesystemServer,
  loadConfig,
  loadCredentials,
  saveCredentials,
} from "./config.js";
import { Tunnel } from "./tunnel.js";

export async function runUp(): Promise<void> {
  const creds = loadCredentials();
  if (!creds?.refreshToken)
    throw new Error("not paired — run: gaia bridge login");
  if (loadConfig().servers.length === 0) {
    throw new Error("no servers configured — run: gaia bridge add");
  }
  if (getFilesystemServer()?.allowWrite) {
    console.error(
      "[gaia bridge] filesystem WRITES are enabled for this device.",
    );
  }

  const token = await exchangeToken(creds.apiUrl, creds.refreshToken);
  // Persist the rotated token before anything else can use the old one.
  saveCredentials({ ...creds, refreshToken: token.refresh_token });
  for (const server of loadConfig().servers) {
    await registerServer(
      creds.apiUrl,
      token.access_token,
      server.key,
      server.name,
    );
  }

  const tunnel = new Tunnel({ ...creds, refreshToken: token.refresh_token });
  const shutdown = async () => {
    console.error("\n[gaia bridge] shutting down…");
    await tunnel.stop();
    process.exit(0);
  };
  process.on("SIGINT", () => void shutdown());
  process.on("SIGTERM", () => void shutdown());
  await tunnel.run();
}

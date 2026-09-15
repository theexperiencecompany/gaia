// Thin HTTP client for the device-bridge REST endpoints.

import type {
  DeviceTokenResponse,
  ErrorEnvelope,
  PollPairingResponse,
  StartPairingResponse,
} from "../api/generated/index.js";
import type { ServerConfig } from "./config.types.js";

export type { DeviceTokenResponse, PollPairingResponse, StartPairingResponse };

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function post<T>(
  apiUrl: string,
  path: string,
  body: unknown,
  token?: string,
): Promise<T> {
  const res = await fetch(`${apiUrl}/api/v1${path}`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const envelope = (await res.json()) as ErrorEnvelope;
      if (envelope.message) message = envelope.message;
    } catch {
      // non-JSON error body; keep the status line
    }
    throw new ApiError(message, res.status);
  }
  return (await res.json()) as T;
}

async function del<T>(apiUrl: string, path: string, token: string): Promise<T> {
  const res = await fetch(`${apiUrl}/api/v1${path}`, {
    method: "DELETE",
    headers: { authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const envelope = (await res.json()) as ErrorEnvelope;
      if (envelope.message) message = envelope.message;
    } catch {
      // non-JSON error body; keep the status line
    }
    throw new ApiError(message, res.status);
  }
  return (await res.json()) as T;
}

export function startPairing(
  apiUrl: string,
  name: string,
  platform: string,
  daemonVersion: string,
): Promise<StartPairingResponse> {
  return post(apiUrl, "/device/pair/start", {
    name,
    platform,
    daemon_version: daemonVersion,
  });
}

export function pollPairing(
  apiUrl: string,
  deviceCode: string,
): Promise<PollPairingResponse> {
  return post(apiUrl, "/device/pair/poll", { device_code: deviceCode });
}

export function exchangeToken(
  apiUrl: string,
  refreshToken: string,
): Promise<DeviceTokenResponse> {
  return post(apiUrl, "/device/token", { refresh_token: refreshToken });
}

export function registerServer(
  apiUrl: string,
  accessToken: string,
  serverKey: string,
  displayName: string,
  kind: ServerConfig["type"],
): Promise<{ integration_id: string; server_key: string }> {
  return post(
    apiUrl,
    "/device/servers",
    { server_key: serverKey, display_name: displayName, kind },
    accessToken,
  );
}

export function deregisterServer(
  apiUrl: string,
  accessToken: string,
  serverKey: string,
): Promise<{ server_key: string; removed: boolean }> {
  return del(
    apiUrl,
    `/device/servers/${encodeURIComponent(serverKey)}`,
    accessToken,
  );
}

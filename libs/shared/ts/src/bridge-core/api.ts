// Thin HTTP client for the device-bridge REST endpoints.

import { ApiError, REQUEST_ID_HEADER } from "../api/apiError.js";
import type {
  DeviceTokenResponse,
  PollPairingResponse,
  StartPairingResponse,
} from "../api/generated/index.js";
import type { ServerConfig } from "./config.types.js";

export type { DeviceTokenResponse, PollPairingResponse, StartPairingResponse };
export { ApiError };

/** Read the response, or raise the API's own words as an ApiError. */
async function readOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const raw = await res.text();
    let body: unknown = raw;
    try {
      body = JSON.parse(raw);
    } catch {
      // non-JSON error body; the raw text is what the envelope check sees
    }
    throw ApiError.fromBody(res.status, body, {
      fallbackMessage: `${res.status} ${res.statusText}`,
      requestId: res.headers.get(REQUEST_ID_HEADER) ?? undefined,
    });
  }
  return (await res.json()) as T;
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
  return readOrThrow<T>(res);
}

async function del<T>(apiUrl: string, path: string, token: string): Promise<T> {
  const res = await fetch(`${apiUrl}/api/v1${path}`, {
    method: "DELETE",
    headers: { authorization: `Bearer ${token}` },
  });
  return readOrThrow<T>(res);
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

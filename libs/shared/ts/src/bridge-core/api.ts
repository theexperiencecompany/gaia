// Thin HTTP client for the device-bridge REST endpoints.

import {
  ApiError,
  mediaType,
  REQUEST_ID_HEADER,
  toErrorEnvelope,
} from "../api/apiError.js";
import type {
  DeviceTokenResponse,
  PollPairingResponse,
  StartPairingResponse,
} from "../api/generated/index.js";
import type { ServerConfig } from "./config.types.js";
import { bridgeLogger } from "./env.js";

export type { DeviceTokenResponse, PollPairingResponse, StartPairingResponse };
export { ApiError };

/** Read the response, or raise the API's own words as an ApiError. */
async function readOrThrow<T>(
  res: Response,
  url: string,
  method: string,
): Promise<T> {
  if (!res.ok) {
    const raw = await res.text();
    let body: unknown = raw;
    try {
      body = JSON.parse(raw);
    } catch {
      // non-JSON error body; the raw text is what the envelope check sees
    }
    const requestId = res.headers.get(REQUEST_ID_HEADER) ?? undefined;
    const envelope = toErrorEnvelope(body);

    if (!envelope) {
      // A body that isn't GAIA's envelope came from whatever answered this URL —
      // a dev web server, a proxy error page, or a redirect's destination
      // (res.url). Record it for the daemon's log.
      const answeredAt = res.url || url;
      const contentType = mediaType(res);
      bridgeLogger().error(
        `[gaia bridge] ${method} ${new URL(answeredAt).pathname} → ${res.status} ${contentType}, not GAIA's envelope`,
        {
          url: answeredAt,
          requestedUrl: url,
          status: res.status,
          contentType,
          requestId,
          body: raw.slice(0, 300),
        },
      );
      const redirectNote =
        answeredAt === url ? "" : `; the request went to ${url}`;
      throw ApiError.fromBody(res.status, body, {
        fallbackMessage:
          `${res.status} ${res.statusText} from ${answeredAt} (${contentType}) — ` +
          `not the GAIA API's JSON error body${redirectNote}`,
        requestId,
      });
    }

    throw ApiError.fromBody(res.status, body, { requestId });
  }
  return (await res.json()) as T;
}

async function post<T>(
  apiUrl: string,
  path: string,
  body: unknown,
  token?: string,
): Promise<T> {
  const url = `${apiUrl}/api/v1${path}`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  });
  return readOrThrow<T>(res, url, "POST");
}

async function del<T>(apiUrl: string, path: string, token: string): Promise<T> {
  const url = `${apiUrl}/api/v1${path}`;
  const res = await fetch(url, {
    method: "DELETE",
    headers: { authorization: `Bearer ${token}` },
  });
  return readOrThrow<T>(res, url, "DELETE");
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

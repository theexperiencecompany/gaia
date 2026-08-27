// Thin HTTP client for the device-bridge REST endpoints.

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface StartPairingResponse {
  device_code: string;
  user_code: string;
  verification_url: string;
  expires_in: number;
  interval: number;
}

export interface PollPairingResponse {
  status: "pending" | "approved" | "denied" | "expired";
  device_id: string | null;
  refresh_token: string | null;
}

export interface DeviceTokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  refresh_token: string;
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
    let detail = `${res.status} ${res.statusText}`;
    try {
      const data = (await res.json()) as { detail?: string };
      if (data.detail) detail = data.detail;
    } catch {
      // non-JSON error body; keep the status line
    }
    throw new ApiError(detail, res.status);
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
): Promise<{ integration_id: string; server_key: string }> {
  return post(
    apiUrl,
    "/device/servers",
    { server_key: serverKey, display_name: displayName },
    accessToken,
  );
}

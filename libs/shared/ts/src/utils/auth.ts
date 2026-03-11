export interface TokenStorage {
  getToken(): string | null | Promise<string | null>;
  setToken(token: string): void | Promise<void>;
  removeToken(): void | Promise<void>;
}

export interface JwtPayload {
  exp: number;
  sub: string;
  [key: string]: unknown;
}

export function parseJwt(token: string): JwtPayload | null {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) {
      return null;
    }

    const base64Payload = parts[1];
    const base64 = base64Payload.replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64.padEnd(
      base64.length + ((4 - (base64.length % 4)) % 4),
      "=",
    );

    let decoded: string;
    if (typeof atob !== "undefined") {
      decoded = atob(padded);
    } else {
      decoded = Buffer.from(padded, "base64").toString("utf-8");
    }

    const parsed: unknown = JSON.parse(decoded);

    if (
      !parsed ||
      typeof parsed !== "object" ||
      Array.isArray(parsed)
    ) {
      return null;
    }

    const obj = parsed as Record<string, unknown>;

    if (typeof obj.exp !== "number" || typeof obj.sub !== "string") {
      return null;
    }

    return obj as JwtPayload;
  } catch {
    return null;
  }
}

export function isTokenExpired(token: string): boolean {
  const payload = parseJwt(token);
  if (!payload) {
    return true;
  }

  const nowInSeconds = Math.floor(Date.now() / 1000);
  return payload.exp <= nowInSeconds;
}

export function shouldRefreshToken(
  token: string,
  bufferSeconds: number = 300,
): boolean {
  const payload = parseJwt(token);
  if (!payload) {
    return true;
  }

  const nowInSeconds = Math.floor(Date.now() / 1000);
  return payload.exp <= nowInSeconds + bufferSeconds;
}

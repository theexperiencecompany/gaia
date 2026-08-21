import { useEffect, useState } from "react";
import { browserApi } from "../api/browserApi";

// The live view is served from a friendly vhost the host-only session cookie is
// not sent to, so a token is required for every connection. Fetch it once per
// session (cookie auth works same-origin to the API); the token's lifetime
// bounds the socket, which comfortably covers a single browser task.
export function useLiveViewToken(
  sessionId: string | null | undefined,
): string | null {
  const [token, setToken] = useState<string | null>(null);
  useEffect(() => {
    if (!sessionId) return undefined;
    let active = true;
    browserApi.getLiveViewToken(sessionId).then((res) => {
      if (active && res) setToken(res.token);
    });
    return () => {
      active = false;
    };
  }, [sessionId]);
  return token;
}

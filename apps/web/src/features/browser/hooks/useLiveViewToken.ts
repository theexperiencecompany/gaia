import { useEffect, useState } from "react";
import { browserApi } from "../api/browserApi";

// The live view's vhost never sees the session cookie, so every connection
// carries a token: minted once per session (cookie auth is same-origin to the
// API), and its lifetime bounds the socket.
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

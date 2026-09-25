import { useCallback, useEffect, useState } from "react";
import { browserApi } from "../api/browserApi";

const COUNTDOWN_TICK_MS = 1000;

/** Mints the single-use `gaia-connect` code and counts down its life; call
 * `mint` again once it expires. */
export function useImportToken() {
  const [token, setToken] = useState<string | null>(null);
  // The expiry instant is captured at mint time, not derived on render, so a
  // re-render never restarts the clock.
  const [expiresAt, setExpiresAt] = useState<number | null>(null);
  const [secondsLeft, setSecondsLeft] = useState(0);
  const [isMinting, setIsMinting] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const mint = useCallback(async () => {
    setIsMinting(true);
    setError(null);
    try {
      const data = await browserApi.mintImportToken();
      setToken(data.token);
      setExpiresAt(Date.now() + data.expires_in_seconds * 1000);
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setIsMinting(false);
    }
  }, []);

  useEffect(() => {
    if (expiresAt === null) return undefined;
    const tick = () =>
      setSecondsLeft(Math.max(0, Math.ceil((expiresAt - Date.now()) / 1000)));
    tick();
    const id = setInterval(tick, COUNTDOWN_TICK_MS);
    return () => clearInterval(id);
  }, [expiresAt]);

  const reset = useCallback(() => {
    setToken(null);
    setError(null);
    setExpiresAt(null);
    setSecondsLeft(0);
  }, []);

  return {
    token,
    secondsLeft,
    isExpired: expiresAt !== null && secondsLeft <= 0,
    isMinting,
    error,
    mint,
    reset,
  };
}

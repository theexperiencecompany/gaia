import { useCallback, useEffect, useRef, useState } from "react";
import { browserApi } from "@/features/browser/api/browserApi";
import type { BrowserHandoffStatus } from "@/types/features/browserTaskTypes";

export type SettledHandoffStatus = Exclude<BrowserHandoffStatus, "pending">;

/**
 * Decision state for one pending handoff, shared by the chat card's prompt and
 * the browser side panel. Polls until the handoff reaches a terminal status —
 * including after our own decision, so an in-flight "Stopping…" can never spin
 * forever — and settles immediately from the decision response when possible.
 */
export function useHandoffDecision(
  handoffId: string,
  onSettled?: (status: SettledHandoffStatus) => void,
) {
  const [decided, setDecided] = useState<"continue" | "cancel" | null>(null);
  const [pending, setPending] = useState(false);
  const [serverStatus, setServerStatus] = useState<BrowserHandoffStatus | null>(
    null,
  );

  const settled =
    serverStatus && serverStatus !== "pending" ? serverStatus : null;

  // Read through a ref so a parent passing a new closure never restarts polling.
  const onSettledRef = useRef(onSettled);
  useEffect(() => {
    onSettledRef.current = onSettled;
  }, [onSettled]);
  const settle = useCallback((status: BrowserHandoffStatus) => {
    if (status === "pending") return;
    setServerStatus(status);
    onSettledRef.current?.(status);
  }, []);

  useEffect(() => {
    if (settled) return undefined;
    let active = true;
    const poll = async () => {
      const res = await browserApi.getHandoffStatus(handoffId);
      if (active && res) settle(res.status);
    };
    const id = setInterval(poll, 3000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [settled, handoffId, settle]);

  const decide = async (decision: "continue" | "cancel", message?: string) => {
    setPending(true);
    setDecided(decision);
    try {
      const res = await browserApi.postHandoffDecision(
        handoffId,
        decision,
        message,
      );
      if (res) settle(res.status);
    } catch {
      setDecided(null);
    } finally {
      setPending(false);
    }
  };

  return { decide, decided, pending, settled };
}

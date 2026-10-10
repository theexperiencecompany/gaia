"use client";

import { redirect } from "next/navigation";
import type { ReactNode } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import { useElectron } from "@/hooks/useElectron";
import { usePathname } from "@/i18n/navigation";

interface ElectronRouteGuardProps {
  children: ReactNode;
}

/**
 * Route guard that handles automatic navigation in Electron environment.
 * - Redirects from landing page to login or chat based on auth state
 * - Signals to Electron main process when the app is ready
 *
 * IMPORTANT: We wait for user data to load before making redirect decisions
 * to avoid the double-redirect cascade ("/" -> "/login" -> "/c")
 */
export function ElectronRouteGuard({ children }: ElectronRouteGuardProps) {
  const { isElectron, signalReady } = useElectron();
  const pathname = usePathname();
  const user = useCurrentUser();
  const signaledReadyRef = useRef(false);
  const [isUserCheckComplete, setIsUserCheckComplete] = useState(false);

  // Idempotent wrapper: `signalReady` is fire-and-forget IPC that must fire
  // once per window. The root-page gate below may re-execute after an
  // aborted pass (redirect() throws), so the guard lives here, not in render.
  const signalReadyOnce = useCallback(() => {
    if (signaledReadyRef.current) return;
    signaledReadyRef.current = true;
    signalReady();
  }, [signalReady]);

  // Track when user check is complete — `useCurrentUser()` reads a persisted store
  // that rehydrates synchronously on the client, so one pass after mount in
  // Electron is enough before we commit to a redirect decision.
  useEffect(() => {
    if (isElectron) setIsUserCheckComplete(true);
  }, [isElectron]);

  // Signal ready immediately for non-root pages
  useEffect(() => {
    if (!isElectron || pathname === "/") return;

    signalReadyOnce();
  }, [isElectron, pathname, signalReadyOnce]);

  // For root ("/"), redirect at render time (no landing-page flash) once the
  // user check completes — `redirect()` throws, so code after it is
  // unreachable; both calls are idempotent so a replayed render can't double-fire.
  if (isElectron && pathname === "/" && isUserCheckComplete) {
    signalReadyOnce();
    redirect(user?.email ? "/c" : "/desktop-login");
  }

  return <>{children}</>;
}

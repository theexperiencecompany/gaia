"use client";

import { redirect } from "next/navigation";
import type { ReactNode } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useUser } from "@/features/auth/hooks/useUser";
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
  const user = useUser();
  const signaledReadyRef = useRef(false);
  const [isUserCheckComplete, setIsUserCheckComplete] = useState(false);

  // Idempotent wrapper: `signalReady` is a fire-and-forget IPC that must be
  // sent exactly once per window. The render-time root-page gate below may
  // re-execute after an aborted pass (redirect() throws), so the once-guard
  // lives inside this callback — where ref writes are allowed — instead of
  // mutating refs during render.
  const signalReadyOnce = useCallback(() => {
    if (signaledReadyRef.current) return;
    signaledReadyRef.current = true;
    signalReady();
  }, [signalReady]);

  // Track when user check is complete — `useUser()` reads a persisted store
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

  // For the root page ("/"), wait for the user check, then redirect at render
  // time so there is no intermediate flash of the landing page. `redirect()`
  // performs a replace-style client navigation and throws, so everything after
  // it in this branch is unreachable by design. The branch stays pure: both
  // calls are idempotent (same-target redirect; latched signalReadyOnce), so a
  // replayed render cannot double-fire them.
  if (isElectron && pathname === "/" && isUserCheckComplete) {
    signalReadyOnce();
    redirect(user?.email ? "/c" : "/desktop-login");
  }

  return <>{children}</>;
}

"use client";

import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";

import { useUser } from "@/features/auth/hooks/useUser";
import { useElectron } from "@/hooks/useElectron";

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
  const router = useRouter();
  const pathname = usePathname();
  const user = useUser();
  const hasSignaledReady = useRef(false);
  const hasRedirected = useRef(false);
  const [isUserCheckComplete, setIsUserCheckComplete] = useState(false);

  // Track when user check is complete (either we have user data or we've waited long enough)
  useEffect(() => {
    if (!isElectron) return;

    // If user has email, they're authenticated - check complete
    if (user?.email) {
      setIsUserCheckComplete(true);
      return;
    }

    setIsUserCheckComplete(true);
  }, [isElectron, user?.email]);

  useEffect(() => {
    // Only run in Electron environment
    if (!isElectron) return;

    // For non-root pages, signal ready immediately
    if (pathname !== "/") {
      if (!hasSignaledReady.current) {
        signalReady();
        hasSignaledReady.current = true;
      }
      return;
    }

    // For root page ("/"), wait for user check before redirecting
    if (pathname === "/" && isUserCheckComplete && !hasRedirected.current) {
      hasRedirected.current = true;

      if (user?.email) {
        router.replace("/c");
      } else {
        router.replace("/login");
      }

      // Signal ready after redirect is initiated
      // The redirect page will render and show content
      if (!hasSignaledReady.current) {
        signalReady();
        hasSignaledReady.current = true;
      }
    }
  }, [
    isElectron,
    pathname,
    user?.email,
    router,
    signalReady,
    isUserCheckComplete,
  ]);

  return <>{children}</>;
}

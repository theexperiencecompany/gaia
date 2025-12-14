"use client";

import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { useEffect, useRef } from "react";

import { useUser } from "@/features/auth/hooks/useUser";
import { useElectron } from "@/hooks/useElectron";

interface ElectronRouteGuardProps {
  children: ReactNode;
}

/**
 * Route guard that handles automatic navigation in Electron environment.
 * - Redirects from landing page to login or chat based on auth state
 * - Signals to Electron main process when the app is ready
 */
export function ElectronRouteGuard({ children }: ElectronRouteGuardProps) {
  const { isElectron, signalReady } = useElectron();
  const router = useRouter();
  const pathname = usePathname();
  const user = useUser();
  const hasSignaledReady = useRef(false);

  useEffect(() => {
    // Only run in Electron environment
    if (!isElectron) return;

    // If on landing page in Electron, redirect appropriately
    if (pathname === "/") {
      if (user?.email) {
        // User is logged in, go to chat
        router.replace("/c");
      } else {
        // User not logged in, go to login
        router.replace("/login");
      }
      return; // Don't signal ready yet, wait for redirect
    }

    // Signal ready once per session when we're on a proper page
    if (!hasSignaledReady.current) {
      // Small delay to ensure the page is rendered
      const timer = setTimeout(() => {
        signalReady();
        hasSignaledReady.current = true;
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [isElectron, pathname, user?.email, router, signalReady]);

  return <>{children}</>;
}

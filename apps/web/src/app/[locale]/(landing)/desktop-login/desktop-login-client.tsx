"use client";

import { Button } from "@heroui/button";
import { Spinner } from "@heroui/spinner";
import { CancelCircleIcon } from "@icons";
import type { DesktopServerFormReason } from "@shared/desktop-tools";
import Image from "next/image";
import { RedirectType, redirect, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowUpRight } from "@/components/shared/icons";
import { RaisedButton } from "@/components/ui/raised-button";
import { authApi } from "@/features/auth/api/authApi";
import { useElectron } from "@/hooks/useElectron";
import { track } from "@/lib/analytics";
import { getElectronAPI } from "@/lib/electron/api";
import { SelfHostServerForm } from "./self-host-server-form";

interface DesktopLoginClientProps {
  /** True when a self-hosted server (AUTH_MODE=local) serves this page: the
   * desktop app loaded the server itself, which signs in at its own /login. */
  isSelfHosted: boolean;
  /** Why the desktop app opened this page on its server form (tray or a
   * failed server load), or null for a normal launch. */
  serverFormReason: DesktopServerFormReason | null;
}

/**
 * Desktop Login Page
 *
 * A polished, centered login page for the desktop app. On GAIA Cloud it opens
 * the system browser for OAuth and waits for the deep link callback, and offers
 * connecting to a self-hosted server instead. Located in (landing) to avoid
 * sidebar layout.
 */
export function DesktopLoginClient({
  isSelfHosted,
  serverFormReason,
}: DesktopLoginClientProps) {
  const { isElectron, openExternal, signalReady } = useElectron();
  const router = useRouter();
  const [status, setStatus] = useState<
    "ready" | "opened" | "waiting" | "redirecting" | "signed-out" | "error"
  >("ready");
  const [showServerForm, setShowServerForm] = useState(
    serverFormReason !== null,
  );
  const [selfHostOrigin, setSelfHostOrigin] = useState<string | null>(null);

  useEffect(() => {
    if (isSelfHosted) return;
    let cancelled = false;
    getElectronAPI()
      ?.getDesktopSettings()
      .then(({ settings }) => {
        if (!cancelled) setSelfHostOrigin(settings.selfHostOrigin);
      })
      .catch((error: unknown) => {
        console.error("Failed to read the desktop settings:", error);
      });
    return () => {
      cancelled = true;
    };
  }, [isSelfHosted]);

  // Redirect to normal login if not in Electron (after brief check)
  useEffect(() => {
    if (typeof window === "undefined") return;

    const timeout = setTimeout(() => {
      if (!isElectron) {
        router.replace("/login");
      }
    }, 1000);

    return () => clearTimeout(timeout);
  }, [isElectron, router]);

  // A persisted session (either auth mode) skips the login screen. The splash
  // stays up until something signals ready: on success that is /c's
  // ElectronRouteGuard, on failure here. A requested server form never skips.
  useEffect(() => {
    if (!isElectron) return;
    if (serverFormReason !== null) {
      signalReady();
      return;
    }
    let cancelled = false;
    authApi
      .fetchUserInfo()
      .then(() => {
        if (!cancelled) setStatus("redirecting");
      })
      .catch(() => {
        if (cancelled) return;
        signalReady();
        if (isSelfHosted) setStatus("signed-out");
      });
    return () => {
      cancelled = true;
    };
  }, [isElectron, isSelfHosted, serverFormReason, signalReady]);

  // Listen for the main process signalling it's about to navigate to /c
  useEffect(() => {
    if (typeof window === "undefined" || !window.api?.onAuthRedirecting) return;
    const cleanup = window.api.onAuthRedirecting(() => {
      setStatus("redirecting");
    });
    return cleanup;
  }, []);

  // Resolved during render, not an effect, so this screen never paints before
  // navigating to the app.
  if (status === "redirecting") {
    redirect("/c", RedirectType.replace);
  }
  if (status === "signed-out") {
    redirect("/login", RedirectType.replace);
  }

  const handleOpenLogin = () => {
    const apiBaseUrl =
      process.env.NEXT_PUBLIC_API_BASE_URL || "https://api.heygaia.io/api/v1/";
    const loginUrl = `${apiBaseUrl}oauth/login/workos/desktop`;

    track("navigation:cta_clicked", {
      location: "desktop_login_page",
      destination: "workos_oauth",
    });

    try {
      openExternal(loginUrl);
      setStatus("opened");

      // After a short delay, show waiting state
      setTimeout(() => {
        setStatus("waiting");
      }, 1500);
    } catch (error) {
      console.error("Failed to open external URL:", error);
      setStatus("error");
    }
  };

  return (
    <div className="flex min-h-screen w-full items-center justify-center bg-black">
      <div className="relative z-10 w-full max-w-xl px-6">
        <div className="rounded-4xl bg-zinc-100/10 p-8 backdrop-blur-lg flex items-center flex-col">
          <div className="mb-8 flex justify-center">
            <Image
              // src="/images/logos/macos.png"
              src={"/images/screenshots/desktop_dock.png"}
              alt="GAIA"
              width={700}
              height={100}
              priority
              className="rounded-2xl"
            />
          </div>

          <h1 className="mb-2 text-center text-4xl font-semibold text-white">
            Welcome to GAIA Desktop
          </h1>
          <p className="mb-8 text-center text-zinc-300 text-xl font-light">
            Sign in to your account to continue
          </p>

          {isSelfHosted ? (
            <div className="flex justify-center py-4">
              <Spinner color="primary" />
            </div>
          ) : selfHostOrigin ? (
            <SelfHostServerForm
              currentOrigin={selfHostOrigin}
              unreachable={serverFormReason === "unreachable"}
            />
          ) : (
            <>
              {status === "ready" && (
                <RaisedButton
                  color="#00bbff"
                  className="w-fit gap-3 text-black!"
                  onClick={handleOpenLogin}
                >
                  <ArrowUpRight className="h-5 w-5" />
                  Open Login in Browser
                </RaisedButton>
              )}

              {status === "opened" && (
                <div className="flex flex-col items-center gap-4 py-4">
                  <Spinner color="primary" />
                  <p className="text-center text-sm text-zinc-400">
                    Opening your browser...
                  </p>
                </div>
              )}

              {status === "waiting" && (
                <div className="flex flex-col items-center gap-4 py-4">
                  <Spinner color="primary" />
                  <div className="text-center">
                    <p className="font-medium text-white">
                      Complete login in your browser
                    </p>
                    <p className="mt-1 text-sm text-zinc-400">
                      You&apos;ll be redirected back automatically
                    </p>
                  </div>
                  <Button
                    variant="light"
                    size="sm"
                    className="mt-2 text-zinc-500"
                    onPress={() => setStatus("ready")}
                  >
                    Try again
                  </Button>
                </div>
              )}

              {status === "error" && (
                <div className="flex flex-col items-center gap-4 py-4">
                  <div className="flex h-12 w-12 items-center justify-center rounded-full bg-red-500/20">
                    <CancelCircleIcon
                      size={24}
                      className="text-red-400"
                      aria-hidden="true"
                    />
                  </div>
                  <p className="text-center text-red-400">
                    Failed to open browser
                  </p>
                  <Button
                    variant="flat"
                    size="sm"
                    onPress={() => setStatus("ready")}
                  >
                    Try Again
                  </Button>
                </div>
              )}

              <div className="mt-6 flex w-full justify-center">
                {showServerForm ? (
                  <SelfHostServerForm
                    currentOrigin={null}
                    unreachable={false}
                  />
                ) : (
                  <Button
                    variant="light"
                    size="sm"
                    radius="full"
                    className="text-zinc-400"
                    onPress={() => setShowServerForm(true)}
                  >
                    Use my own server
                  </Button>
                )}
              </div>
            </>
          )}
        </div>

        {/* Footer text */}
        <p className="mt-6 text-center text-xs text-zinc-500 font-light">
          By signing in, you agree to our Terms of Service and Privacy Policy
        </p>
      </div>
    </div>
  );
}

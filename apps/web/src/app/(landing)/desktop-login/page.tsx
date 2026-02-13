"use client";

import Image from "next/image";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowUpRight } from "@/components/shared/icons";
import { RaisedButton } from "@/components/ui/raised-button";
import Spinner from "@/components/ui/spinner";
import HeroImage from "@/features/landing/components/hero/HeroImage";
import {
  getTimeOfDay,
  type TimeOfDay,
} from "@/features/landing/utils/timeOfDay";
import { useElectron } from "@/hooks/useElectron";

/**
 * Desktop Login Page
 *
 * A polished, centered login page for the desktop app.
 * Opens system browser for OAuth and waits for deep link callback.
 * Located in (landing) to avoid sidebar layout.
 */
export default function DesktopLoginPage() {
  const { isElectron, openExternal } = useElectron();
  const router = useRouter();
  const [timeOfDay, setTimeOfDay] = useState<TimeOfDay | null>(null);
  const [status, setStatus] = useState<
    "ready" | "opened" | "waiting" | "error"
  >("ready");

  useEffect(() => {
    setTimeOfDay(getTimeOfDay());
  }, []);

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

  const handleOpenLogin = () => {
    const apiBaseUrl =
      process.env.NEXT_PUBLIC_API_BASE_URL || "https://api.heygaia.io/api/v1/";
    const loginUrl = `${apiBaseUrl}oauth/login/workos/desktop`;

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
    <div className="relative flex min-h-screen w-full items-center justify-center">
      <div className="fixed inset-0 z-0 opacity-60">
        <HeroImage timeOfDay={timeOfDay} />
      </div>

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
          <p className="mb-8 text-center text-zinc-400 text-xl font-light">
            Sign in to your account to continue
          </p>

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
              <Spinner />
              <p className="text-center text-zinc-400">
                Opening your browser...
              </p>
            </div>
          )}

          {status === "waiting" && (
            <div className="flex flex-col items-center gap-4 py-4">
              <div className="relative">
                <div className="h-12 w-12 animate-pulse rounded-full bg-emerald-500/20" />
                <div className="absolute inset-0 flex items-center justify-center">
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    width="24"
                    height="24"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    className="text-emerald-400"
                    aria-hidden="true"
                  >
                    <path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z" />
                    <path d="m9 12 2 2 4-4" />
                  </svg>
                </div>
              </div>
              <div className="text-center">
                <p className="font-medium text-white">
                  Complete login in your browser
                </p>
                <p className="mt-1 text-sm text-zinc-500">
                  You&apos;ll be redirected back automatically
                </p>
              </div>
              <button
                type="button"
                onClick={() => setStatus("ready")}
                className="mt-2 text-sm text-zinc-500 underline-offset-4 hover:text-zinc-300 hover:underline"
              >
                Try again
              </button>
            </div>
          )}

          {status === "error" && (
            <div className="flex flex-col items-center gap-4 py-4">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-red-500/20">
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  width="24"
                  height="24"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="text-red-400"
                  aria-hidden="true"
                >
                  <circle cx="12" cy="12" r="10" />
                  <line x1="15" y1="9" x2="9" y2="15" />
                  <line x1="9" y1="9" x2="15" y2="15" />
                </svg>
              </div>
              <p className="text-center text-red-400">Failed to open browser</p>
              <button
                type="button"
                onClick={() => setStatus("ready")}
                className="rounded-lg bg-zinc-800 px-4 py-2 text-sm text-white transition-colors hover:bg-zinc-700"
              >
                Try Again
              </button>
            </div>
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

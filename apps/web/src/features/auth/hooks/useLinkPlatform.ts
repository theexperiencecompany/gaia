"use client";

import { useIsRestoring } from "@tanstack/react-query";
import confetti from "canvas-confetti";
import { useEffect, useState } from "react";

import {
  BOT_PLATFORM_ICONS,
  BOT_PLATFORM_LABELS,
  isBotPlatform,
} from "@/config/botPlatforms";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { getErrorFix, getErrorMessage } from "@/lib/api/errors";
import { api } from "@/lib/api/typed";
import { toast } from "@/lib/toast";

/** Copy for a failure the backend did not describe itself. */
function fallbackMessage(status: number | undefined): string {
  if (status === 409) return "This account is already linked.";
  if (status === 400) {
    return "Invalid or expired link. Please request a new one from the bot.";
  }
  return "Failed to link account. Please try again.";
}

/**
 * The backend's own words for a failed link, read through the shared
 * extractor: `AppError` serialises `{ message, why, fix }` at the top level of
 * the body, so a hand-rolled `data.detail` read finds nothing and every
 * failure degrades to generic copy. The `fix` is appended because it is the
 * half that tells the user what to do next.
 */
function resolveError(err: unknown): string {
  const response = (err as { response?: { status?: number; data?: unknown } })
    ?.response;
  const message =
    getErrorMessage(response?.data) ?? fallbackMessage(response?.status);
  const fix = getErrorFix(response?.data);
  return fix ? `${message} ${fix}` : message;
}

/** Celebrate a successful link with a quick confetti burst. */
function useLinkConfetti(isLinked: boolean) {
  useEffect(() => {
    if (!isLinked) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const defaults = {
      spread: 70,
      ticks: 90,
      gravity: 1,
      decay: 0.92,
      startVelocity: 32,
      colors: ["#00bbff", "#3effa6", "#ffffff", "#a78bfa"],
    };
    confetti({ ...defaults, particleCount: 60, origin: { x: 0.5, y: 0.45 } });
    confetti({ ...defaults, particleCount: 30, origin: { x: 0.5, y: 0.45 } });
  }, [isLinked]);
}

/** The platform-link flow: who the token belongs to, and linking it. */
export function useLinkPlatform(platform: string | null, token: string | null) {
  const { isAuthenticated } = useAuth();

  const [isLinking, setIsLinking] = useState(false);
  const [isLinked, setIsLinked] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [accountInfo, setAccountInfo] = useState<{
    username?: string | null;
    displayName?: string | null;
  } | null>(null);

  // The persisted query cache restores asynchronously, so every auth decision
  // must wait for it — otherwise a signed-in user is briefly judged signed out.
  const hasHydrated = !useIsRestoring();

  const config =
    platform && isBotPlatform(platform)
      ? {
          name: BOT_PLATFORM_LABELS[platform],
          iconSrc: BOT_PLATFORM_ICONS[platform],
        }
      : null;

  useEffect(() => {
    if (token) {
      api
        .get("/api/v1/bot/link-token-info/{token}", {
          path: { token },
          silent: true,
        })
        .then(({ username, display_name }) => {
          setAccountInfo({
            username,
            displayName: display_name,
          });
        })
        .catch((err) => {
          // Non-critical enrichment (account display name only). Log without
          // surfacing a toast — the link flow works fine without it.
          console.error("Failed to load link-token info:", err);
        });
    }
  }, [token]);

  useLinkConfetti(isLinked);

  const handleLink = async () => {
    if (!platform || !token) return;
    setIsLinking(true);
    setError(null);
    try {
      await api.post("/api/v1/platform-links/{platform}", {
        path: { platform },
        body: { token },
        silent: true,
      });
      setIsLinked(true);
      toast.success("Account linked successfully!");
    } catch (err: unknown) {
      setError(resolveError(err));
    } finally {
      setIsLinking(false);
    }
  };

  return {
    isAuthenticated,
    hasHydrated,
    config,
    accountInfo,
    error,
    isLinking,
    isLinked,
    handleLink,
  };
}

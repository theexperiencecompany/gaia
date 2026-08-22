"use client";

import { Spinner } from "@heroui/spinner";
import { CheckmarkCircle02Icon, Link01Icon } from "@icons";
import confetti from "canvas-confetti";
import Image from "next/image";
import { RedirectType, redirect } from "next/navigation";
import { useEffect, useState, useSyncExternalStore } from "react";
import { RaisedButton } from "@/components/ui/raised-button";
import {
  BOT_PLATFORM_ICONS,
  BOT_PLATFORM_LABELS,
  isBotPlatform,
} from "@/config/botPlatforms";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { apiService } from "@/lib/api/service";
import { toast } from "@/lib/toast";
import { useUserStore } from "@/stores/userStore";

/** Shared card shell: rounded, flat, no outline, no shadow — matches GAIA surfaces. */
function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full items-center justify-center p-4">
      <div className="w-full max-w-md rounded-3xl bg-zinc-900 p-8 text-center">
        {children}
      </div>
    </div>
  );
}

interface LinkPlatformClientProps {
  platform: string | null;
  token: string | null;
}

// The auth store rehydrates from persisted storage asynchronously (zustand
// persist), so every auth decision must wait for hydration. Reading the status
// with useSyncExternalStore is render-safe: no post-paint flash, and the
// component re-renders the moment hydration finishes.
function subscribeToUserStoreHydration(onStoreChange: () => void): () => void {
  return useUserStore.persist.onFinishHydration(onStoreChange);
}

function getUserStoreHydrationSnapshot(): boolean {
  return useUserStore.persist.hasHydrated();
}

// Server render has no storage — treat as unhydrated so it renders nothing,
// matching the client's first paint.
function getServerHydrationSnapshot(): boolean {
  return false;
}

export default function LinkPlatformClient({
  platform,
  token,
}: Readonly<LinkPlatformClientProps>) {
  const { isAuthenticated } = useAuth();

  const [isLinking, setIsLinking] = useState(false);
  const [isLinked, setIsLinked] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [accountInfo, setAccountInfo] = useState<{
    username?: string;
    displayName?: string;
  } | null>(null);

  const hasHydrated = useSyncExternalStore(
    subscribeToUserStoreHydration,
    getUserStoreHydrationSnapshot,
    getServerHydrationSnapshot,
  );

  const config =
    platform && isBotPlatform(platform)
      ? {
          name: BOT_PLATFORM_LABELS[platform],
          iconSrc: BOT_PLATFORM_ICONS[platform],
        }
      : null;

  useEffect(() => {
    if (token) {
      apiService
        .get(`/bot/link-token-info/${encodeURIComponent(token)}`, {
          silent: true,
        })
        .then((data) => {
          const { username, display_name } = data as {
            username?: string;
            display_name?: string;
          };
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

  // Celebrate a successful link with a quick confetti burst.
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

  if (!token || !platform || !config) {
    return (
      <Card>
        <p className="text-zinc-400">
          Invalid or expired link. Request a new one from your bot with{" "}
          <span className="font-mono text-zinc-300">/auth</span>.
        </p>
      </Card>
    );
  }

  if (!hasHydrated) {
    return null;
  }

  // Unauthenticated once the store has rehydrated — go sign in and come back.
  // Resolved during render (not in an effect) so this page never paints before
  // navigating; `redirect` performs the same client-side navigation
  // router.replace did.
  if (!isAuthenticated) {
    const returnUrl = `/auth/link-platform?platform=${encodeURIComponent(platform)}&token=${encodeURIComponent(token)}`;
    redirect(
      `/login?return_url=${encodeURIComponent(returnUrl)}`,
      RedirectType.replace,
    );
  }

  const handleLink = async () => {
    setIsLinking(true);
    setError(null);
    try {
      await apiService.post(
        `/platform-links/${platform}`,
        { token },
        { silent: true },
      );
      setIsLinked(true);
      toast.success("Account linked successfully!");
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response
        ?.status;
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;

      if (status === 409) {
        setError(detail || "This account is already linked.");
      } else if (status === 400) {
        setError(
          detail ||
            "Invalid or expired link. Please request a new one from the bot.",
        );
      } else {
        setError("Failed to link account. Please try again.");
      }
    } finally {
      setIsLinking(false);
    }
  };

  if (isLinked) {
    return (
      <Card>
        <div className="mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-full bg-success/15">
          <CheckmarkCircle02Icon className="h-9 w-9 text-success" />
        </div>
        <h2 className="mb-2 text-xl font-semibold text-white">
          You&apos;re connected!
        </h2>
        <p className="text-sm text-zinc-400">
          Your {config.name} account is linked. Head back to {config.name} and
          say hi — GAIA&apos;s ready when you are.
        </p>
      </Card>
    );
  }

  return (
    <Card>
      <Image
        src={config.iconSrc}
        alt={`${config.name} icon`}
        width={64}
        height={64}
        className="mx-auto mb-5 h-16 w-16"
      />
      <h2 className="mb-2 text-xl font-semibold text-white">
        Connect {config.name} to GAIA
      </h2>
      {(accountInfo?.displayName || accountInfo?.username) && (
        <p className="mb-1 text-sm font-medium text-zinc-300">
          {accountInfo.displayName ?? accountInfo.username}
          {accountInfo.username && accountInfo.displayName ? (
            <span className="ml-1 text-zinc-500">@{accountInfo.username}</span>
          ) : null}
        </p>
      )}
      <p className="mb-6 text-sm text-zinc-400">
        Chat with GAIA, your personal AI assistant, right inside {config.name}.
        Fully synced with your account.
      </p>

      {error && <p className="mb-4 text-sm text-red-400">{error}</p>}

      <RaisedButton
        size="lg"
        color="#00bbff"
        className="w-full font-medium text-black!"
        onClick={handleLink}
        disabled={isLinking}
      >
        {isLinking ? (
          <Spinner size="sm" color="default" />
        ) : (
          <Link01Icon className="h-5 w-5" />
        )}
        Connect {config.name}
      </RaisedButton>
    </Card>
  );
}

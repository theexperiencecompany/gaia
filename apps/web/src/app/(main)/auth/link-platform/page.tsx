"use client";

import { Button } from "@heroui/button";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import {
  DiscordIcon,
  SlackIcon,
  TelegramIcon,
  WhatsappIcon,
} from "@/components/shared/icons";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { apiService } from "@/lib/api";
import { toast } from "@/lib/toast";

const PLATFORM_CONFIG: Record<
  string,
  {
    name: string;
    icon: React.ComponentType<React.SVGProps<SVGSVGElement>>;
    color: string;
  }
> = {
  discord: { name: "Discord", icon: DiscordIcon, color: "bg-[#5865F2]" },
  slack: { name: "Slack", icon: SlackIcon, color: "bg-[#4A154B]" },
  telegram: { name: "Telegram", icon: TelegramIcon, color: "bg-[#0088cc]" },
  whatsapp: { name: "WhatsApp", icon: WhatsappIcon, color: "bg-[#25D366]" },
};

export default function LinkPlatformPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { isAuthenticated } = useAuth();
  const platform = searchParams.get("platform");
  const token = searchParams.get("token");

  const [isLinking, setIsLinking] = useState(false);
  const [isLinked, setIsLinked] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [accountInfo, setAccountInfo] = useState<{
    username?: string;
    displayName?: string;
  } | null>(null);
  // Guard: only redirect after the Zustand persist store has rehydrated.
  // Without this, the initial render always sees isAuthenticated=false
  // (persist middleware hydrates asynchronously), sending even authenticated
  // users to /login in an infinite loop.
  //
  // Using useState (not useRef) so that setting true triggers a re-render,
  // giving the store one full cycle to rehydrate before the auth check runs.
  const [hasMounted, setHasMounted] = useState(false);

  const config = platform ? PLATFORM_CONFIG[platform] : null;

  useEffect(() => {
    setHasMounted(true);
  }, []);

  useEffect(() => {
    if (!hasMounted) return;
    if (!isAuthenticated && platform && token && config) {
      const returnUrl = `/auth/link-platform?platform=${encodeURIComponent(platform)}&token=${encodeURIComponent(token)}`;
      router.replace(`/login?return_url=${encodeURIComponent(returnUrl)}`);
    }
  }, [hasMounted, isAuthenticated, platform, token, config, router]);

  useEffect(() => {
    if (token) {
      apiService
        .get(`/bot/link-token-info/${token}`, { silent: true })
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
        .catch(() => {});
    }
  }, [token]);

  if (!token || !platform || !config) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="w-full max-w-md rounded-xl border border-zinc-800 bg-zinc-900 p-8 text-center">
          <p className="text-zinc-400">
            Invalid or expired link. Please request a new link from your bot
            using <span className="font-mono text-zinc-300">/auth</span>.
          </p>
        </div>
      </div>
    );
  }

  if (!hasMounted) {
    return null;
  }

  if (!isAuthenticated) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-zinc-400">Redirecting to sign in...</p>
      </div>
    );
  }

  const Icon = config.icon;

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
      <div className="flex h-full items-center justify-center">
        <div className="w-full max-w-md rounded-xl border border-zinc-800 bg-zinc-900 p-8 text-center">
          <div
            className={`mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-xl ${config.color}`}
          >
            <Icon className="h-7 w-7 text-white" />
          </div>
          <h2 className="mb-2 text-xl font-semibold text-white">
            Account Linked!
          </h2>
          <p className="text-zinc-400">
            You can close this window and return to {config.name}.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full items-center justify-center">
      <div className="w-full max-w-md rounded-xl border border-zinc-800 bg-zinc-900 p-8 text-center">
        <div
          className={`mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-xl ${config.color}`}
        >
          <Icon className="h-7 w-7 text-white" />
        </div>
        <h2 className="mb-2 text-xl font-semibold text-white">
          Link your {config.name} account to GAIA?
        </h2>
        {(accountInfo?.displayName || accountInfo?.username) && (
          <p className="mb-1 text-sm font-medium text-zinc-300">
            Account: {accountInfo.displayName ?? accountInfo.username}
            {accountInfo.username && accountInfo.displayName
              ? ` (@${accountInfo.username})`
              : ""}
          </p>
        )}
        <p className="mb-6 text-sm text-zinc-400">
          This will connect your {config.name} account so you can use GAIA
          directly from {config.name}.
        </p>

        {error && <p className="mb-4 text-sm text-red-400">{error}</p>}

        <Button
          color="primary"
          className="w-full"
          onPress={handleLink}
          isLoading={isLinking}
        >
          Confirm Link
        </Button>
      </div>
    </div>
  );
}

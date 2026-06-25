"use client";

import { Spinner } from "@heroui/spinner";
import { CheckmarkCircle02Icon, Link01Icon } from "@icons";
import confetti from "canvas-confetti";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import {
  DiscordIcon,
  SlackIcon,
  TelegramIcon,
  WhatsappIcon,
} from "@/components/shared/icons";
import { RaisedButton } from "@/components/ui/raised-button";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { apiService } from "@/lib/api/service";
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

  // Celebrate a successful link with a quick confetti burst.
  useEffect(() => {
    if (!isLinked) return;
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

  if (!hasMounted) {
    return null;
  }

  if (!isAuthenticated) {
    return (
      <Card>
        <p className="text-sm text-zinc-400">Redirecting to sign in…</p>
      </Card>
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
      <div
        className={`mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-[1.25rem] shadow-lg ${config.color}`}
      >
        <Icon className="h-8 w-8 text-white" />
      </div>
      <h2 className="mb-2 text-xl font-semibold text-white">
        Connect {config.name} to GAIA
      </h2>
      {(accountInfo?.displayName || accountInfo?.username) && (
        <p className="mb-1 text-sm font-medium text-zinc-300">
          {accountInfo.displayName ?? accountInfo.username}
          {accountInfo.username && accountInfo.displayName
            ? ` · @${accountInfo.username}`
            : ""}
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

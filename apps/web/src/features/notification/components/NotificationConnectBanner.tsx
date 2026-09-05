"use client";

import { Button } from "@heroui/button";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { apiService } from "@/lib/api/service";
import type { PlatformLink } from "@/types/platform";
import {
  NOTIFICATION_PLATFORM_ICONS,
  NOTIFICATION_PLATFORM_LABELS,
  NOTIFICATION_PLATFORMS,
} from "../constants";

interface NotificationConnectBannerProps {
  variant?: "compact" | "full";
}

function platformIconStack(size: number) {
  return (
    <div className="flex shrink-0 -space-x-2">
      {NOTIFICATION_PLATFORMS.map((p, index) => (
        <Image
          key={p}
          src={NOTIFICATION_PLATFORM_ICONS[p]}
          alt={NOTIFICATION_PLATFORM_LABELS[p]}
          width={size}
          height={size}
          className={`${index % 2 === 0 ? "-rotate-12" : "rotate-12"} rounded-md`}
        />
      ))}
    </div>
  );
}

export function NotificationConnectBanner({
  variant = "compact",
}: NotificationConnectBannerProps) {
  const router = useRouter();
  const [platformLinks, setPlatformLinks] = useState<
    Record<string, PlatformLink | null>
  >({});
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    apiService
      .get<{ platform_links: Record<string, PlatformLink | null> }>(
        "/platform-links",
        { silent: true },
      )
      .then((data) => {
        setPlatformLinks(data.platform_links || {});
      })
      .catch(() => {
        // Silently fail — banner is non-critical
      })
      .finally(() => {
        setIsLoading(false);
      });
  }, []);

  if (isLoading) return null;

  const unconnectedPlatforms = NOTIFICATION_PLATFORMS.filter(
    (p) => !platformLinks[p]?.platformUserId,
  );

  if (unconnectedPlatforms.length === 0) return null;

  if (variant === "compact") {
    return (
      <div className="w-full px-3">
        <div className="flex w-full items-center justify-between gap-3 rounded-xl bg-zinc-800/60 px-3 py-2">
          <div className="flex items-center gap-3">
            {platformIconStack(26)}
            <span className="text-xs text-zinc-400">
              Get notified in the apps you already use
            </span>
          </div>
          <Button
            size="sm"
            variant="flat"
            color="primary"
            className="shrink-0 rounded-xl text-xs"
            onPress={() => router.push("/settings/linked-accounts")}
          >
            Connect
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-between gap-4 rounded-2xl bg-zinc-800/60 p-4">
      <div className="flex items-center gap-4">
        {platformIconStack(32)}
        <div>
          <p className="text-sm font-medium text-zinc-100">
            Stay notified on your devices
          </p>
          <p className="mt-0.5 text-xs text-zinc-400">
            Connect Telegram, Discord, WhatsApp, or Slack to get GAIA
            notifications anywhere.
          </p>
        </div>
      </div>
      <Button
        size="sm"
        variant="flat"
        color="primary"
        className="shrink-0 rounded-xl text-xs"
        onPress={() => router.push("/settings/linked-accounts")}
      >
        Connect
      </Button>
    </div>
  );
}

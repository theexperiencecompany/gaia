"use client";

import { Button } from "@heroui/button";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { apiService } from "@/lib/api";
import type { PlatformLink } from "@/types/platform";
import {
  NOTIFICATION_PLATFORM_LABELS,
  NOTIFICATION_PLATFORMS,
} from "../constants";

interface NotificationConnectBannerProps {
  variant?: "compact" | "full";
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

  const platformList = unconnectedPlatforms
    .map((p) => NOTIFICATION_PLATFORM_LABELS[p])
    .join(" and ");

  if (variant === "compact") {
    return (
      <div className="flex items-center justify-between gap-2 rounded-xl border border-zinc-700 bg-zinc-800/60 px-3 py-2 text-xs">
        <span className="text-zinc-400">
          Connect {platformList} to receive push notifications.
        </span>
        <Button
          size="sm"
          variant="flat"
          color="primary"
          className="shrink-0 text-xs"
          onPress={() => router.push("/settings?section=linked-accounts")}
        >
          Connect
        </Button>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-zinc-700 bg-zinc-800/60 p-4">
      <p className="text-sm font-medium text-zinc-200">
        Stay notified on your devices
      </p>
      <p className="mt-1 text-xs text-zinc-400">
        Connect {platformList} to receive GAIA notifications outside the web
        app.
      </p>
      <Button
        size="sm"
        variant="flat"
        color="primary"
        className="mt-3 text-xs"
        onPress={() => router.push("/settings?section=linked-accounts")}
      >
        Connect platforms
      </Button>
    </div>
  );
}

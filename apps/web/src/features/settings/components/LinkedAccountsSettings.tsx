"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Switch } from "@heroui/switch";
import Image from "next/image";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { TelegramIcon } from "@/components/shared/icons";
import { SettingsCard } from "@/features/settings/components/SettingsCard";
import { apiService } from "@/lib/api";
import { NotificationsAPI } from "@/services/api/notifications";

interface PlatformLink {
  platform: "discord" | "slack" | "telegram" | "whatsapp";
  platformUserId: string;
  username?: string;
  displayName?: string;
  connectedAt?: string;
}

interface PlatformConfig {
  id: string;
  name: string;
  image?: string;
  color: string;
  description: string;
  connectedDescription: string;
}

const PLATFORMS: PlatformConfig[] = [
  {
    id: "discord",
    name: "Discord",
    image: "/images/icons/macos/discord.webp",
    color: "#5865F2",
    description: "Use GAIA directly from Discord servers and DMs",
    connectedDescription: "Use /gaia in Discord to chat with GAIA",
  },
  {
    id: "slack",
    name: "Slack",
    image: "/images/icons/macos/slack.webp",
    color: "#4A154B",
    description: "Bring GAIA into your Slack workspace",
    connectedDescription: "Use /gaia in Slack to chat with GAIA",
  },
  {
    id: "telegram",
    name: "Telegram",
    description: "Chat with GAIA on Telegram",
    image: "/images/icons/macos/telegram.webp",
    color: "#0088cc",
    connectedDescription: "Message your bot on Telegram to chat with GAIA",
  },
  // {
  //   id: "whatsapp",
  //   name: "WhatsApp",
  //   image: "/images/icons/macos/whatsapp.webp",
  //   color: "#25D366",
  //   description: "Connect GAIA to WhatsApp (Beta)",
  //   connectedDescription: "Message GAIA on WhatsApp",
  // },
];

const NOTIFICATION_PLATFORMS = new Set(["telegram", "discord"]);

export default function LinkedAccountsSettings() {
  const [platformLinks, setPlatformLinks] = useState<
    Record<string, PlatformLink | null>
  >({});
  const [isLoading, setIsLoading] = useState(true);
  const [connectingPlatform, setConnectingPlatform] = useState<string | null>(
    null,
  );
  const [channelPrefs, setChannelPrefs] = useState<{
    telegram: boolean;
    discord: boolean;
  }>({ telegram: true, discord: true });
  const [prefsLoading, setPrefsLoading] = useState(true);
  const [togglingPlatform, setTogglingPlatform] = useState<string | null>(null);

  useEffect(() => {
    fetchPlatformLinks();
    fetchChannelPrefs();
  }, []);

  const fetchChannelPrefs = async () => {
    try {
      setPrefsLoading(true);
      const prefs = await NotificationsAPI.getChannelPreferences();
      setChannelPrefs(prefs);
    } catch {
      // silently ignore — toggles will still render with default true
    } finally {
      setPrefsLoading(false);
    }
  };

  const handleToggleNotification = async (
    platform: "telegram" | "discord",
    enabled: boolean,
  ) => {
    setTogglingPlatform(platform);
    try {
      await NotificationsAPI.updateChannelPreference(platform, enabled);
      setChannelPrefs((prev) => ({ ...prev, [platform]: enabled }));
    } catch {
      toast.error(`Failed to update ${platform} notification preference`);
    } finally {
      setTogglingPlatform(null);
    }
  };

  const fetchPlatformLinks = async () => {
    try {
      setIsLoading(true);
      const data = await apiService.get<{
        platform_links: Record<string, PlatformLink | null>;
      }>("/platform-links", { silent: true });
      setPlatformLinks(data.platform_links || {});
    } catch {
      toast.error("Failed to load connected accounts");
    } finally {
      setIsLoading(false);
    }
  };

  const handleConnect = async (platformId: string) => {
    try {
      setConnectingPlatform(platformId);

      const data = await apiService.get<{
        auth_url?: string;
        instructions?: string;
        auth_type: string;
      }>(`/platform-links/${platformId}/connect`, { silent: true });

      if (data.auth_url) {
        const width = 600;
        const height = 700;
        const left = window.screen.width / 2 - width / 2;
        const top = window.screen.height / 2 - height / 2;

        const popup = window.open(
          data.auth_url,
          `Connect ${platformId}`,
          `width=${width},height=${height},left=${left},top=${top}`,
        );

        const pollTimer = setInterval(() => {
          if (popup?.closed) {
            clearInterval(pollTimer);
            fetchPlatformLinks();
            setConnectingPlatform(null);
          }
        }, 500);
      } else if (data.instructions && platformId === "telegram") {
        toast.info(data.instructions, { duration: 8000 });
        setConnectingPlatform(null);
      } else {
        setConnectingPlatform(null);
      }
    } catch {
      toast.error(`Failed to connect ${platformId}`);
      setConnectingPlatform(null);
    }
  };

  const handleDisconnect = async (platformId: string) => {
    try {
      await apiService.delete(`/platform-links/${platformId}`, {
        silent: true,
      });
      toast.success(`Disconnected from ${platformId}`);
      await fetchPlatformLinks();
    } catch {
      toast.error(`Failed to disconnect from ${platformId}`);
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h3 className="text-lg font-semibold text-white flex items-center gap-2">
          <span>Linked Accounts</span>
          <Chip color="success" variant="bordered" size="sm">
            Beta
          </Chip>
        </h3>
        <p className="mt-1 text-sm text-zinc-400">
          Connect your messaging platforms to use GAIA from anywhere
        </p>
      </div>

      <SettingsCard>
        <div className="divide-y divide-zinc-800">
          {PLATFORMS.map((platform) => {
            const isConnected =
              platformLinks[platform.id]?.platformUserId != null;

            return (
              <div
                key={platform.id}
                className="flex items-center justify-between py-4 first:pt-0 last:pb-0"
              >
                <div className="flex items-center gap-4">
                  <div
                    className="flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-xl"
                    style={
                      platform.image
                        ? undefined
                        : { backgroundColor: platform.color }
                    }
                  >
                    {platform.image ? (
                      <Image
                        src={platform.image}
                        alt={platform.name}
                        width={44}
                        height={44}
                        className="h-full w-full object-cover"
                      />
                    ) : (
                      <TelegramIcon className="h-6 w-6 text-white" />
                    )}
                  </div>

                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-white">
                        {platform.name}
                      </span>
                      {isConnected && (
                        <span className="flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs font-medium text-emerald-400">
                          <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                          Connected
                        </span>
                      )}
                    </div>
                    <p className="mt-0.5 text-xs text-zinc-500">
                      {isConnected
                        ? platform.connectedDescription
                        : platform.description}
                    </p>
                    {isConnected &&
                      (platformLinks[platform.id]?.displayName ||
                        platformLinks[platform.id]?.username) && (
                        <p className="mt-0.5 text-xs text-zinc-600">
                          {platformLinks[platform.id]?.displayName
                            ? `${platformLinks[platform.id]?.displayName}${platformLinks[platform.id]?.username ? ` (@${platformLinks[platform.id]?.username})` : ""}`
                            : `@${platformLinks[platform.id]?.username}`}
                        </p>
                      )}
                  </div>
                </div>

                <div className="ml-4 flex shrink-0 items-center gap-3">
                  {isConnected && NOTIFICATION_PLATFORMS.has(platform.id) && (
                    <div className="flex flex-col items-center gap-0.5">
                      <Switch
                        size="sm"
                        isSelected={
                          channelPrefs[platform.id as "telegram" | "discord"]
                        }
                        isDisabled={
                          prefsLoading || togglingPlatform === platform.id
                        }
                        onValueChange={(enabled) =>
                          handleToggleNotification(
                            platform.id as "telegram" | "discord",
                            enabled,
                          )
                        }
                        aria-label={`Enable ${platform.name} notifications`}
                      />
                      <span className="text-[10px] text-zinc-500">Notify</span>
                    </div>
                  )}
                  {isConnected ? (
                    <Button
                      variant="flat"
                      color="danger"
                      size="sm"
                      onPress={() => handleDisconnect(platform.id)}
                      isDisabled={isLoading}
                      className="text-xs"
                    >
                      Disconnect
                    </Button>
                  ) : (
                    <Button
                      variant="flat"
                      color="primary"
                      size="sm"
                      onPress={() => handleConnect(platform.id)}
                      isLoading={connectingPlatform === platform.id}
                      isDisabled={isLoading || connectingPlatform != null}
                      className="text-xs"
                    >
                      Connect
                    </Button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </SettingsCard>

      <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
        <h4 className="mb-2 text-xs font-medium uppercase tracking-wider text-zinc-500">
          How it works
        </h4>
        <ul className="space-y-1.5 text-sm text-zinc-400">
          <li className="flex items-start gap-2">
            <span className="mt-0.5 text-zinc-600">•</span>
            Connect your account using the button above
          </li>
          <li className="flex items-start gap-2">
            <span className="mt-0.5 text-zinc-600">•</span>
            Use{" "}
            <code className="rounded bg-zinc-800 px-1 py-0.5 text-xs text-zinc-300">
              /gaia
            </code>{" "}
            in Discord or Slack, or just message the Telegram bot
          </li>
          <li className="flex items-start gap-2">
            <span className="mt-0.5 text-zinc-600">•</span>
            All conversations sync with your GAIA account
          </li>
          <li className="flex items-start gap-2">
            <span className="mt-0.5 text-zinc-600">•</span>
            Disconnect anytime from this page
          </li>
        </ul>
      </div>
    </div>
  );
}

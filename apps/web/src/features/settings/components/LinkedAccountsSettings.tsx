"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import Image from "next/image";
import { useEffect, useState } from "react";
import {
  SettingsPage,
  SettingsRow,
  SettingsSection,
} from "@/features/settings/components/ui";
import { apiService } from "@/lib/api";
import { toast } from "@/lib/toast";
import type { PlatformLink } from "@/types/platform";

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

export default function LinkedAccountsSettings() {
  const [platformLinks, setPlatformLinks] = useState<
    Record<string, PlatformLink | null>
  >({});
  const [isLoading, setIsLoading] = useState(true);
  const [connectingPlatform, setConnectingPlatform] = useState<string | null>(
    null,
  );
  useEffect(() => {
    fetchPlatformLinks();
  }, []);

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
    <SettingsPage>
      <SettingsSection description="Connect your messaging platforms to use GAIA from anywhere.">
        {PLATFORMS.map((platform) => {
          const isConnected =
            platformLinks[platform.id]?.platformUserId != null;
          const link = platformLinks[platform.id];
          const userLabel = link?.displayName
            ? `${link.displayName}${link.username ? ` (@${link.username})` : ""}`
            : link?.username
              ? `@${link.username}`
              : undefined;

          return (
            <SettingsRow
              key={platform.id}
              label={platform.name}
              description={
                isConnected
                  ? userLabel
                    ? `${platform.connectedDescription} · ${userLabel}`
                    : platform.connectedDescription
                  : platform.description
              }
              icon={
                platform.image ? (
                  <Image
                    src={platform.image}
                    alt={platform.name}
                    width={36}
                    height={36}
                    className="rounded-xl"
                  />
                ) : undefined
              }
            >
              <div className="flex items-center gap-3">
                {isConnected && (
                  <span className="flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs font-medium text-emerald-400">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                    Connected
                  </span>
                )}
                <Button
                  variant="flat"
                  color={isConnected ? "danger" : "primary"}
                  size="sm"
                  onPress={() =>
                    isConnected
                      ? handleDisconnect(platform.id)
                      : handleConnect(platform.id)
                  }
                  isLoading={connectingPlatform === platform.id}
                  isDisabled={isLoading || connectingPlatform != null}
                  className="text-xs"
                >
                  {isConnected ? "Disconnect" : "Connect"}
                </Button>
              </div>
            </SettingsRow>
          );
        })}
      </SettingsSection>

      <SettingsSection title="How it works">
        <div className="px-4 py-3.5">
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
      </SettingsSection>
    </SettingsPage>
  );
}

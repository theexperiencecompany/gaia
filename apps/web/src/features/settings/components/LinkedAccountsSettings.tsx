"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Input } from "@heroui/input";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import Image from "next/image";
import { useEffect, useRef, useState } from "react";
import { BOT_PLATFORM_ICONS, BOT_PLATFORM_LABELS } from "@/config/botPlatforms";
import { useUserSubscriptionStatus } from "@/features/pricing/hooks/usePricing";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { apiService } from "@/lib/api/service";
import { toast } from "@/lib/toast";
import { usePricingModalStore } from "@/stores/pricingModalStore";
import type { PlatformLink } from "@/types/platform";

const E164_PHONE_PATTERN = /^\+[1-9]\d{6,14}$/;

interface PlatformConfig {
  id: string;
  name: string;
  image?: string;
  color: string;
  description: string;
  connectedDescription: string;
  premium?: boolean;
  requiresPhone?: boolean;
}

const PLATFORMS: PlatformConfig[] = [
  {
    id: "telegram",
    name: BOT_PLATFORM_LABELS.telegram,
    description: "Chat with GAIA on Telegram",
    image: BOT_PLATFORM_ICONS.telegram,
    color: "#0088cc",
    connectedDescription: "Message your bot on Telegram to chat with GAIA",
  },
  {
    id: "whatsapp",
    name: BOT_PLATFORM_LABELS.whatsapp,
    image: BOT_PLATFORM_ICONS.whatsapp,
    color: "#25D366",
    description: "Connect GAIA to WhatsApp (Beta)",
    connectedDescription: "Message GAIA on WhatsApp",
  },
  {
    id: "imessage",
    name: BOT_PLATFORM_LABELS.imessage,
    image: BOT_PLATFORM_ICONS.imessage,
    color: "#34C759",
    description: "Text GAIA over iMessage (Pro)",
    connectedDescription: "Message GAIA from your iPhone or Mac",
    premium: true,
    requiresPhone: true,
  },
  {
    id: "slack",
    name: BOT_PLATFORM_LABELS.slack,
    image: BOT_PLATFORM_ICONS.slack,
    color: "#4A154B",
    description: "Bring GAIA into your Slack workspace",
    connectedDescription: "Use /gaia in Slack to chat with GAIA",
  },
  {
    id: "discord",
    name: BOT_PLATFORM_LABELS.discord,
    image: BOT_PLATFORM_ICONS.discord,
    color: "#5865F2",
    description: "Use GAIA directly from Discord servers and DMs",
    connectedDescription: "Use /gaia in Discord to chat with GAIA",
  },
];

export default function LinkedAccountsSettings() {
  const [platformLinks, setPlatformLinks] = useState<
    Record<string, PlatformLink | null>
  >({});
  const [isLoading, setIsLoading] = useState(true);
  const [connectingPlatform, setConnectingPlatform] = useState<string | null>(
    null,
  );
  const [phoneModalPlatform, setPhoneModalPlatform] = useState<string | null>(
    null,
  );
  const [phone, setPhone] = useState("");
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const { data: subscriptionStatus } = useUserSubscriptionStatus();
  const openPricingModal = usePricingModalStore((s) => s.openModal);

  const clearPollTimer = () => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  };

  useEffect(() => {
    void fetchPlatformLinks();
    return () => {
      clearPollTimer();
    };
  }, []);

  const fetchPlatformLinks = async (): Promise<Record<
    string,
    PlatformLink | null
  > | null> => {
    try {
      setIsLoading(true);
      const data = await apiService.get<{
        platform_links: Record<string, PlatformLink | null>;
      }>("/platform-links", { silent: true });
      setPlatformLinks(data.platform_links || {});
      return data.platform_links || {};
    } catch {
      toast.error("Failed to load connected accounts");
      return null;
    } finally {
      setIsLoading(false);
    }
  };

  const startConnect = (platform: PlatformConfig) => {
    if (platform.premium && !subscriptionStatus?.is_subscribed) {
      openPricingModal();
      return;
    }
    if (platform.requiresPhone) {
      setPhone("");
      setPhoneModalPlatform(platform.id);
      return;
    }
    handleConnect(platform.id);
  };

  const handleConnect = async (platformId: string, phoneNumber?: string) => {
    try {
      setConnectingPlatform(platformId);

      const wasConnected = platformLinks[platformId]?.platformUserId != null;

      const data = await apiService.post<{
        auth_url?: string;
        instructions?: string;
        action_link?: string;
        auth_type: string;
      }>(
        `/platform-links/${platformId}/connect`,
        phoneNumber ? { phone: phoneNumber } : {},
        { silent: true },
      );

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

        clearPollTimer();
        pollTimerRef.current = setInterval(() => {
          if (popup?.closed) {
            clearPollTimer();
            void fetchPlatformLinks().then((links) => {
              if (
                !wasConnected &&
                links?.[platformId]?.platformUserId != null
              ) {
                trackEvent(ANALYTICS_EVENTS.BOT_CONNECTED, {
                  bot_id: platformId,
                });
              }
              setConnectingPlatform(null);
            });
          }
        }, 500);
      } else if (data.auth_type === "manual" && data.instructions) {
        const platformConfig = PLATFORMS.find((p) => p.id === platformId);
        toast.info(`Connect ${platformConfig?.name ?? platformId}`, {
          description: data.instructions,
          duration: 10000,
          icon: platformConfig?.image ? (
            <Image
              src={platformConfig.image}
              alt={platformConfig.name}
              width={20}
              height={20}
              className="rounded"
            />
          ) : undefined,
          ...(data.action_link && {
            action: {
              label: "Open",
              onClick: () => window.open(data.action_link, "_blank"),
            },
          }),
        });
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
      trackEvent(ANALYTICS_EVENTS.BOT_DISCONNECTED, { bot_id: platformId });
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
                {platform.premium && !subscriptionStatus?.is_subscribed && (
                  <Chip size="sm" variant="flat" color="warning">
                    Pro
                  </Chip>
                )}
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
                      : startConnect(platform)
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
              in Discord or Slack, or just message the Telegram, WhatsApp, or
              iMessage bot
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

      <Modal
        isOpen={phoneModalPlatform != null}
        onClose={() => setPhoneModalPlatform(null)}
        size="sm"
      >
        <ModalContent>
          <ModalHeader>Your phone number</ModalHeader>
          <ModalBody>
            <p className="text-sm text-zinc-400">
              iMessage delivers to registered numbers only, so GAIA needs the
              number you text from.
            </p>
            <Input
              autoFocus
              type="tel"
              placeholder="+15551234567"
              value={phone}
              onValueChange={setPhone}
              isInvalid={phone.length > 0 && !E164_PHONE_PATTERN.test(phone)}
              errorMessage="Use E.164 format, e.g. +15551234567"
            />
          </ModalBody>
          <ModalFooter>
            <Button
              variant="flat"
              size="sm"
              onPress={() => setPhoneModalPlatform(null)}
            >
              Cancel
            </Button>
            <Button
              color="primary"
              size="sm"
              isDisabled={!E164_PHONE_PATTERN.test(phone)}
              onPress={() => {
                const platformId = phoneModalPlatform;
                setPhoneModalPlatform(null);
                if (platformId) handleConnect(platformId, phone);
              }}
            >
              Continue
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </SettingsPage>
  );
}

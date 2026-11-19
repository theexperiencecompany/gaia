"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Image from "next/image";
import {
  type ComponentProps,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import type {
  PhoneLinkModal,
  PhoneLinkTarget,
} from "@/components/shared/PhoneLinkModal";
import {
  BOT_AUTH_COMMAND,
  BOT_PLATFORM_ICONS,
  BOT_PLATFORM_LABELS,
  type BotPlatform,
} from "@/config/botPlatforms";
import { useIsPaid } from "@/features/pricing/hooks/useIsPaid";
import {
  platformLinksApi,
  platformLinksQuery,
} from "@/features/settings/api/platformLinksApi";
import { preferenceKeys } from "@/features/settings/api/queryKeys";
import { LINKED_PLATFORM_DETAILS } from "@/features/settings/constants";
import { useDeployment } from "@/features/settings/hooks/useSetupStatus";
import { apiErrorMessage } from "@/lib/api/errorMessage";
import { toast } from "@/lib/toast";
import { useUpgradeModalStore } from "@/stores/upgradeModalStore";
import type { PlatformLinks } from "@/types/platform";

const POPUP_WIDTH = 600;
const POPUP_HEIGHT = 700;
const POPUP_POLL_MS = 500;
const MANUAL_INSTRUCTIONS_TOAST_MS = 10000;

/** Toast a platform's manual connect steps, with its link when it has one. */
function showManualInstructions(
  platform: BotPlatform,
  instructions: string,
  actionLink: string | null | undefined,
) {
  const name = BOT_PLATFORM_LABELS[platform];
  toast.info(`Connect ${name}`, {
    description: instructions,
    duration: MANUAL_INSTRUCTIONS_TOAST_MS,
    icon: (
      <Image
        src={BOT_PLATFORM_ICONS[platform]}
        alt={name}
        width={20}
        height={20}
        className="rounded"
      />
    ),
    ...(actionLink && {
      action: {
        label: "Open",
        onClick: () => window.open(actionLink, "_blank"),
      },
    }),
  });
}

interface UsePlatformLinks {
  /** Null until the first load succeeds: an empty map would read as "nothing linked". */
  links: PlatformLinks | null;
  isLoading: boolean;
  loadFailed: boolean;
  refetch: () => void;
  isLinked: (platform: BotPlatform) => boolean;
  /** "Name (@handle)", "@handle", or undefined when the link carries neither. */
  linkedAs: (platform: BotPlatform) => string | undefined;
  isLockedBehindPro: (platform: BotPlatform) => boolean;
  connectingPlatform: BotPlatform | null;
  connect: (platform: BotPlatform) => void;
  disconnect: (platform: BotPlatform) => void;
  phoneLinkModal: ComponentProps<typeof PhoneLinkModal>;
}

/** The user's bot platform links and the real connect / disconnect flows for them. */
export function usePlatformLinks(): UsePlatformLinks {
  const queryClient = useQueryClient();
  const { data, isLoading, isError, refetch } = useQuery(platformLinksQuery());
  const links = data?.platform_links ?? null;
  const [connectingPlatform, setConnectingPlatform] =
    useState<BotPlatform | null>(null);
  const [phoneModalPlatform, setPhoneModalPlatform] =
    useState<BotPlatform | null>(null);
  const [phoneLinkTarget, setPhoneLinkTarget] =
    useState<PhoneLinkTarget | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // Registering a number takes a round trip to Photon. Closing the modal (or
  // starting over) invalidates that request, so a late reply cannot drop the
  // previous attempt's number into the session the user is now in.
  const connectAttemptRef = useRef(0);
  const { isPaid, isUnknown } = useIsPaid();
  const billingEnabled = useDeployment().bills;
  const openUpgradeModal = useUpgradeModalStore((s) => s.openModal);

  // Unknown status stays permissive: the backend enforces the gate, and
  // blocking a paying customer is worse than a brief open window.
  const isLockedBehindPro = (platform: BotPlatform) =>
    billingEnabled &&
    !!LINKED_PLATFORM_DETAILS[platform].premium &&
    !isUnknown &&
    !isPaid;

  const clearPollTimer = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const reloadLinks = () =>
    queryClient.invalidateQueries({ queryKey: preferenceKeys.platformLinks });

  useEffect(() => clearPollTimer, [clearPollTimer]);

  const openAuthPopup = (platform: BotPlatform, authUrl: string) => {
    const left = window.screen.width / 2 - POPUP_WIDTH / 2;
    const top = window.screen.height / 2 - POPUP_HEIGHT / 2;
    const popup = window.open(
      authUrl,
      `Connect ${platform}`,
      `width=${POPUP_WIDTH},height=${POPUP_HEIGHT},left=${left},top=${top}`,
    );
    clearPollTimer();
    pollTimerRef.current = setInterval(() => {
      if (popup?.closed) {
        clearPollTimer();
        void reloadLinks().then(() => {
          setConnectingPlatform(null);
        });
      }
    }, POPUP_POLL_MS);
  };

  const requestConnect = async (platform: BotPlatform, phone?: string) => {
    const attempt = ++connectAttemptRef.current;
    try {
      setConnectingPlatform(platform);
      const response = await platformLinksApi.connect(platform, phone);
      if (attempt !== connectAttemptRef.current) return;

      if (response.auth_url) {
        openAuthPopup(platform, response.auth_url);
        return;
      }
      if (response.contact_number) {
        // An sms: deep link resolves on Apple devices only, so the number and
        // the command have to be readable (and copyable) on any device.
        setPhoneLinkTarget({
          contactNumber: response.contact_number,
          command: BOT_AUTH_COMMAND,
          actionLink: response.action_link ?? undefined,
        });
      } else if (response.auth_type === "manual" && response.instructions) {
        showManualInstructions(
          platform,
          response.instructions,
          response.action_link,
        );
      }
      setConnectingPlatform(null);
    } catch (error) {
      if (attempt !== connectAttemptRef.current) return;
      toast.error(`Couldn't connect ${BOT_PLATFORM_LABELS[platform]}`, {
        description: apiErrorMessage(error),
      });
      setConnectingPlatform(null);
    }
  };

  const connect = (platform: BotPlatform) => {
    if (isLockedBehindPro(platform)) {
      openUpgradeModal(undefined, {
        dismissible: true,
        source: "settings_linked_accounts",
      });
      return;
    }
    if (LINKED_PLATFORM_DETAILS[platform].requiresPhone) {
      setPhoneLinkTarget(null);
      setPhoneModalPlatform(platform);
      return;
    }
    void requestConnect(platform);
  };

  const disconnection = useMutation({
    mutationFn: platformLinksApi.disconnect,
    onSuccess: (_response, platform) => {
      toast.success(`Disconnected from ${BOT_PLATFORM_LABELS[platform]}`);
      return reloadLinks();
    },
    onError: (error, platform) =>
      toast.error(`Couldn't disconnect ${BOT_PLATFORM_LABELS[platform]}`, {
        description: apiErrorMessage(error),
      }),
  });

  const isLinked = (platform: BotPlatform) =>
    links?.[platform]?.platformUserId != null;

  const linkedAs = (platform: BotPlatform) => {
    const link = links?.[platform];
    if (link?.displayName)
      return `${link.displayName}${link.username ? ` (@${link.username})` : ""}`;
    return link?.username ? `@${link.username}` : undefined;
  };

  return {
    links,
    isLoading,
    loadFailed: isError,
    refetch: () => void refetch(),
    isLinked,
    linkedAs,
    isLockedBehindPro,
    connectingPlatform,
    connect,
    disconnect: (platform) => disconnection.mutate(platform),
    phoneLinkModal: {
      isOpen: phoneModalPlatform != null,
      platformName: phoneModalPlatform
        ? BOT_PLATFORM_LABELS[phoneModalPlatform]
        : BOT_PLATFORM_LABELS.imessage,
      isSubmitting:
        phoneModalPlatform != null && connectingPlatform === phoneModalPlatform,
      target: phoneLinkTarget,
      onSubmit: (phone) => {
        if (phoneModalPlatform) void requestConnect(phoneModalPlatform, phone);
      },
      onClose: () => {
        connectAttemptRef.current += 1;
        setConnectingPlatform(null);
        setPhoneModalPlatform(null);
        setPhoneLinkTarget(null);
        void reloadLinks();
      },
    },
  };
}

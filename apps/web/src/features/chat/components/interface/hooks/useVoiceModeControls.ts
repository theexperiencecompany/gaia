"use client";

import { useRouter } from "next/navigation";

import { usePrefetchConnectionDetails } from "@/features/chat/components/voice-agent/hooks/useConnectionDetails";
import { useIsPaid } from "@/features/pricing/hooks/useIsPaid";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { syncSingleConversation } from "@/services/syncService";
import { useChatStore } from "@/stores/chatStore";
import { usePricingModalStore } from "@/stores/pricingModalStore";
import {
  useVoiceModeActions,
  useVoiceModeActive,
} from "@/stores/voiceModeStore";

interface UseVoiceModeControlsReturn {
  voiceModeActive: boolean;
  /** Warms the session token on hover so clicking starts ~instantly. */
  onVoiceModeHover: () => void;
  /** Enters voice mode, or shows the upgrade modal to a known-free user. */
  startVoiceMode: () => void;
  endVoiceCall: () => void;
}

/** The paid-only voice-mode gate plus the enter/leave transitions around it. */
export const useVoiceModeControls = (
  convoIdParam: string,
): UseVoiceModeControlsReturn => {
  const router = useRouter();
  const voiceModeActive = useVoiceModeActive();
  const { enterVoiceMode, exitVoiceMode } = useVoiceModeActions();
  const openPricingModal = usePricingModalStore((s) => s.openModal);
  const { isPaid, isUnknown: isSubscriptionStatusUnknown } = useIsPaid();
  const prefetchConnectionDetails = usePrefetchConnectionDetails(
    convoIdParam || undefined,
  );

  // Gated on subscription — /token is plan-limited and free users get the
  // modal. Only warms when we positively know the user is paid; skipping the
  // warm-up while unknown is harmless (no blocking consequence, just a missed
  // prefetch), unlike startVoiceMode below which must never block a paying user.
  const onVoiceModeHover = () => {
    if (isPaid) prefetchConnectionDetails();
  };

  const startVoiceMode = () => {
    // Voice mode is paid-only (the /token endpoint enforces it server-side
    // too). Free users get the upgrade modal instead of a session. While
    // the subscription status is still unknown, let the user proceed —
    // the backend's 402 is the real enforcement, so a brief permissive
    // window here is safe, but wrongly paywalling a paying customer is not.
    if (!isSubscriptionStatusUnknown && !isPaid) {
      trackEvent(ANALYTICS_EVENTS.CHAT_VOICE_MODE_TOGGLED, {
        voice_mode_enabled: false,
        conversation_id: convoIdParam,
        blocked_reason: "upgrade_required",
      });
      openPricingModal();
      return;
    }
    trackEvent(ANALYTICS_EVENTS.CHAT_VOICE_MODE_TOGGLED, {
      voice_mode_enabled: true,
      conversation_id: convoIdParam,
    });
    enterVoiceMode(convoIdParam || undefined);
  };

  const endVoiceCall = () => {
    trackEvent(ANALYTICS_EVENTS.CHAT_VOICE_MODE_TOGGLED, {
      voice_mode_enabled: false,
      conversation_id: convoIdParam,
    });
    // Capture the active id BEFORE exiting (exitVoiceMode clears the store id).
    const activeId = useChatStore.getState().activeConversationId;
    exitVoiceMode();
    if (activeId) {
      // During voice the URL was updated in-place via history.replaceState, so
      // the App Router segment is still /c (convoIdParam undefined for a new
      // chat). A real navigation resolves the conversation route so the
      // just-finished voice chat renders without a manual reload.
      if (!convoIdParam) {
        router.replace(`/c/${activeId}`);
      }
      // Pull server canonical messages so the chat shows them without the
      // in-memory voice turns; prevents duplicate-after-refresh.
      syncSingleConversation(activeId).catch((err) =>
        console.error("[ChatPage] post-voice sync failed", err),
      );
    }
  };

  return { voiceModeActive, onVoiceModeHover, startVoiceMode, endVoiceCall };
};

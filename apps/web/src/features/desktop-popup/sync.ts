"use client";

import { useEffect } from "react";
import {
  type LiveConversation,
  liveConversation,
  useLiveConversationStore,
} from "@/features/chat/live/liveConversationStore";
import type { PaywallSource } from "@/lib/analytics";
import type { IMessage } from "@/lib/db/chatDb";
import { type AuxLoading, useAuxLoadingStore } from "@/stores/auxLoadingStore";
import { useChatStore } from "@/stores/chatStore";
import type { UpgradeOffer } from "@/stores/upgradeModal.types";
import { useUpgradeModalStore } from "@/stores/upgradeModalStore";

/**
 * Cross-window chat state sync for the desktop assistant popup.
 *
 * The popup is two BrowserWindows — the composer pill and the
 * conversation card — each with its own native liquid glass and its own
 * JS context. The composer window owns all chat logic (sending, the
 * conversation's event stream, stores); this channel mirrors the active
 * conversation into the feed window, which is render-only.
 */

const CHANNEL_NAME = "gaia-desktop-popup-chat";

/** Publisher → consumer state snapshot. */
interface PopupChatState {
  type: "state";
  activeConversationId: string | null;
  messages: IMessage[];
  /** The active conversation as its event stream has built it. */
  live: LiveConversation | null;
  /** Auxiliary (voice/upload) loading, mirrored as-is. */
  auxLoading: AuxLoading | null;
  /**
   * Whether the paid-only wall is up, and the offer behind it. The composer
   * window is where a 402 lands (it owns sending), but it is a 420x48 pill
   * with nowhere to render the block — so the state crosses to the feed
   * window, which is content-sized, and surfaces there instead.
   */
  paywallOpen: boolean;
  paywallOffer: UpgradeOffer | null;
  /** Mirrored, never invented here: this window renders someone else's wall. */
  paywallSource: PaywallSource | null;
}

/** Consumer → publisher request for the current snapshot. */
interface PopupChatHello {
  type: "hello";
}

type PopupChatMessage = PopupChatState | PopupChatHello;

/** Trailing-throttle interval for streaming updates, in ms. */
const PUBLISH_THROTTLE_MS = 50;

function snapshot(): PopupChatState {
  const chat = useChatStore.getState();
  const paywall = useUpgradeModalStore.getState();
  const id = chat.activeConversationId;
  return {
    paywallOpen: paywall.open,
    paywallOffer: paywall.offer,
    paywallSource: paywall.source,
    type: "state",
    activeConversationId: id,
    messages: id ? (chat.messagesByConversation[id] ?? []) : [],
    live: id ? liveConversation(id) : null,
    auxLoading: useAuxLoadingStore.getState().auxLoading,
  };
}

/**
 * Mount in the composer window: mirrors every chat and conversation store change
 * (throttled) onto the channel, and answers `hello` requests from a
 * freshly loaded feed window with the current snapshot.
 */
export function usePopupChatPublisher(): void {
  useEffect(() => {
    const channel = new BroadcastChannel(CHANNEL_NAME);
    let timer: ReturnType<typeof setTimeout> | undefined;
    let disposed = false;

    const publish = () => {
      timer = undefined;
      channel.postMessage(snapshot());
    };
    const schedule = () => {
      if (disposed) return;
      if (!timer) timer = setTimeout(publish, PUBLISH_THROTTLE_MS);
    };

    const unsubChat = useChatStore.subscribe(schedule);
    const unsubLive = useLiveConversationStore.subscribe(schedule);
    const unsubAux = useAuxLoadingStore.subscribe(schedule);
    const unsubPaywall = useUpgradeModalStore.subscribe(schedule);
    channel.onmessage = (event: MessageEvent<PopupChatMessage>) => {
      if (event.data?.type === "hello") publish();
    };
    publish();

    return () => {
      disposed = true;
      clearTimeout(timer);
      unsubChat();
      unsubLive();
      unsubAux();
      unsubPaywall();
      channel.close();
    };
  }, []);
}

/**
 * Mount in the feed window: applies published snapshots into this
 * window's local stores so the regular chat rendering pipeline
 * (ChatRenderer, LoadingIndicator) works unchanged.
 */
export function usePopupChatConsumer(): void {
  useEffect(() => {
    const channel = new BroadcastChannel(CHANNEL_NAME);

    channel.onmessage = (event: MessageEvent<PopupChatMessage>) => {
      const data = event.data;
      if (data?.type !== "state") return;

      const chat = useChatStore.getState();
      const paywall = useUpgradeModalStore.getState();
      // Only on change — the snapshots arrive ~20x/sec and openModal would
      // otherwise rewrite the store (and spam devtools) on every one.
      if (data.paywallOpen !== paywall.open) {
        if (data.paywallOpen)
          paywall.openModal(data.paywallOffer ?? undefined, {
            source: data.paywallSource ?? "desktop_popup_mirror",
          });
        else paywall.closeModal({ force: true });
      }
      chat.setActiveConversationId(data.activeConversationId);
      if (data.activeConversationId) {
        chat.setMessagesForConversation(
          data.activeConversationId,
          data.messages,
        );
        if (data.live)
          useLiveConversationStore
            .getState()
            .mirror(data.activeConversationId, data.live);
      }
      useAuxLoadingStore.setState({ auxLoading: data.auxLoading });
    };

    channel.postMessage({ type: "hello" } satisfies PopupChatHello);

    return () => channel.close();
  }, []);
}

"use client";

import { useEffect } from "react";
import type { IMessage } from "@/lib/db/chatDb";
import { type OptimisticMessage, useChatStore } from "@/stores/chatStore";
import { useLoadingStore } from "@/stores/loadingStore";

/**
 * Cross-window chat state sync for the desktop assistant popup.
 *
 * The popup is two BrowserWindows — the composer pill and the
 * conversation card — each with its own native liquid glass and its own
 * JS context. The composer window owns all chat logic (sending,
 * streaming, stores); this channel mirrors the active conversation and
 * loading state into the feed window, which is render-only.
 */

const CHANNEL_NAME = "gaia-desktop-popup-chat";

/** Publisher → consumer state snapshot. */
interface PopupChatState {
  type: "state";
  activeConversationId: string | null;
  messages: IMessage[];
  optimisticMessage: OptimisticMessage | null;
  isLoading: boolean;
  isMainResponseStreaming: boolean;
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
  const loading = useLoadingStore.getState();
  const id = chat.activeConversationId;
  return {
    type: "state",
    activeConversationId: id,
    messages: id ? (chat.messagesByConversation[id] ?? []) : [],
    optimisticMessage: chat.optimisticMessage,
    isLoading: loading.isLoading,
    isMainResponseStreaming: loading.isMainResponseStreaming,
  };
}

/**
 * Mount in the composer window: mirrors every chat/loading store change
 * (throttled) onto the channel, and answers `hello` requests from a
 * freshly loaded feed window with the current snapshot.
 */
export function usePopupChatPublisher(): void {
  useEffect(() => {
    const channel = new BroadcastChannel(CHANNEL_NAME);
    let timer: ReturnType<typeof setTimeout> | null = null;

    const publish = () => {
      timer = null;
      channel.postMessage(snapshot());
    };
    const schedule = () => {
      if (!timer) timer = setTimeout(publish, PUBLISH_THROTTLE_MS);
    };

    const unsubChat = useChatStore.subscribe(schedule);
    const unsubLoading = useLoadingStore.subscribe(schedule);
    channel.onmessage = (event: MessageEvent<PopupChatMessage>) => {
      if (event.data?.type === "hello") publish();
    };
    publish();

    return () => {
      if (timer) clearTimeout(timer);
      unsubChat();
      unsubLoading();
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
      const loading = useLoadingStore.getState();
      chat.setActiveConversationId(data.activeConversationId);
      if (data.activeConversationId) {
        chat.setMessagesForConversation(
          data.activeConversationId,
          data.messages,
        );
      }
      chat.setOptimisticMessage(data.optimisticMessage);
      loading.setIsLoading(data.isLoading);
      loading.setMainResponseStreaming(data.isMainResponseStreaming);
    };

    channel.postMessage({ type: "hello" } satisfies PopupChatHello);

    return () => channel.close();
  }, []);
}

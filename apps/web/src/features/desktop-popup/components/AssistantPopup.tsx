"use client";

import { useQueryClient } from "@tanstack/react-query";
import * as m from "motion/react-m";
import { useEffect, useState } from "react";
import { useUser } from "@/features/auth/hooks/useUser";
import { useConversation } from "@/features/chat/hooks/useConversation";
import { useElectron } from "@/hooks/useElectron";
import { useChatStoreSync } from "@/stores/chatStore";
import { useLoadingStore } from "@/stores/loadingStore";
import {
  POPUP_EASE,
  POPUP_EXPANDED_HEIGHT,
  POPUP_FRAME_PADDING_PX,
  POPUP_TRANSITION_SECONDS,
} from "../constants";
import { usePopupVoice } from "../hooks/usePopupVoice";
import PopupComposer from "./PopupComposer";
import PopupFeed from "./PopupFeed";

/**
 * Siri-style assistant panel rendered inside the Electron popup window.
 *
 * Layout mirrors Siri: the composer (with the orb inside it) sits at the
 * top as its own glass pill, and the conversation renders below it in a
 * separate glass container. The window provides the liquid glass;
 * dismissal is a window-level fade (main process) — content stays
 * mounted so the close is one seamless fade.
 */
export default function AssistantPopup() {
  const { dismissPopup, onPopupActivate, onPopupDeactivate } = useElectron();
  const { agentState, activate, deactivate } = usePopupVoice();
  // 0 = never activated; each activation bumps the key to replay the
  // entrance animation on an already-mounted panel.
  const [activationCount, setActivationCount] = useState(0);
  const queryClient = useQueryClient();
  const user = useUser();
  const isAuthenticated = Boolean(user?.email);

  useChatStoreSync();

  // Outside Electron (browser dev), show the panel immediately.
  useEffect(() => {
    if (typeof window !== "undefined" && !("api" in window)) {
      setActivationCount(1);
    }
  }, []);

  useEffect(() => {
    const offActivate = onPopupActivate(() => {
      setActivationCount((count) => count + 1);
      activate();
      // The popup window loads at app startup, often before the user has
      // signed in — refresh the session on every summon so a login that
      // happened since (main window, deep link) is picked up.
      queryClient.invalidateQueries({ queryKey: ["current-user"] });
    });
    const offDeactivate = onPopupDeactivate(() => {
      // Window-level fade handles the visual exit; just stop the voice
      // session. Content stays mounted for a seamless close.
      deactivate();
    });
    return () => {
      offActivate();
      offDeactivate();
    };
  }, [onPopupActivate, onPopupDeactivate, activate, deactivate, queryClient]);

  useEffect(() => {
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape") return;
      // Never dismiss mid-turn — a streaming response would be lost
      // off-screen and the conversation state would look broken.
      const { isLoading, isMainResponseStreaming } = useLoadingStore.getState();
      if (isLoading || isMainResponseStreaming) return;
      dismissPopup();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [dismissPopup]);

  if (activationCount === 0) return null;

  return (
    <div className="h-screen overflow-hidden text-zinc-100">
      <m.div
        key={activationCount}
        className="flex h-full flex-col gap-3 p-3"
        initial={{ opacity: 0, scale: 0.97, y: -8 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{
          duration: POPUP_TRANSITION_SECONDS,
          ease: POPUP_EASE,
        }}
      >
        <PopupComposer
          active={activationCount > 0}
          agentState={agentState}
          disabled={!isAuthenticated}
        />

        {isAuthenticated && <PopupFeed />}
      </m.div>
      <PopupWindowSizer />
    </div>
  );
}

/**
 * Reports the desired window height to the main process: the bare
 * composer pill when the conversation is empty (no parent panel at
 * all), the full panel once bubbles exist. macOS animates the resize.
 */
function PopupWindowSizer() {
  const { resizePopup } = useElectron();
  const { convoMessages } = useConversation();
  const hasMessages = (convoMessages?.length ?? 0) > 0;

  useEffect(() => {
    if (hasMessages) {
      resizePopup(POPUP_EXPANDED_HEIGHT);
      return;
    }
    const composer = document.querySelector<HTMLElement>(
      "[data-popup-composer]",
    );
    // Composer pill + the frame padding above and below it.
    resizePopup((composer?.offsetHeight ?? 48) + POPUP_FRAME_PADDING_PX * 2);
  }, [hasMessages, resizePopup]);

  return null;
}

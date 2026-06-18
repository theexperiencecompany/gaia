"use client";

import { useQueryClient } from "@tanstack/react-query";
import * as m from "motion/react-m";
import { useEffect, useState } from "react";
import { useUser } from "@/features/auth/hooks/useUser";
import { useElectron } from "@/hooks/useElectron";
import { useChatStore, useChatStoreSync } from "@/stores/chatStore";
import { POPUP_EASE, POPUP_TRANSITION_SECONDS } from "../constants";
import { usePopupEscapeDismiss } from "../hooks/usePopupEscapeDismiss";
import { usePopupVoice } from "../hooks/usePopupVoice";
import { usePopupChatPublisher } from "../sync";
import PopupComposer from "./PopupComposer";

/**
 * Composer island of the assistant popup — a liquid-glass pill in its
 * own window. Owns the entire chat session (sending, streaming, stores)
 * and mirrors it to the conversation window over a BroadcastChannel.
 * Dismissal is a window-level fade (main process); content stays
 * mounted so the close is one seamless fade.
 */
export default function AssistantPopup() {
  const { onPopupActivate, onPopupDeactivate } = useElectron();
  const { agentState, activate, deactivate } = usePopupVoice();
  // 0 = never activated; each activation bumps the key to replay the
  // entrance animation on an already-mounted panel.
  const [activationCount, setActivationCount] = useState(0);
  const queryClient = useQueryClient();
  const user = useUser();
  const isAuthenticated = Boolean(user?.email);

  useChatStoreSync();
  usePopupChatPublisher();
  usePopupEscapeDismiss();

  // Outside Electron (browser dev), show the panel immediately.
  useEffect(() => {
    if (!("api" in globalThis)) {
      setActivationCount(1);
    }
  }, []);

  useEffect(() => {
    const offActivate = onPopupActivate((data) => {
      setActivationCount((count) => count + 1);
      activate(data?.trigger === "wake-word");
      // The popup window loads at app startup, often before the user has
      // signed in — refresh the session on every summon so a login that
      // happened since (main window, deep link) is picked up.
      queryClient.invalidateQueries({ queryKey: ["current-user"] });
    });
    const offDeactivate = onPopupDeactivate(() => {
      // Window-level fade handles the visual exit; stop the voice session
      // and clear the conversation — each summon starts a fresh chat,
      // while messages within one summon accumulate.
      deactivate();
      const chat = useChatStore.getState();
      chat.setActiveConversationId(null);
      chat.setOptimisticMessage(null);
    });
    return () => {
      offActivate();
      offDeactivate();
    };
  }, [onPopupActivate, onPopupDeactivate, activate, deactivate, queryClient]);

  if (activationCount === 0) return null;

  return (
    // Flex-centered so the pill content is optically dead-center no
    // matter what internal spacing the input renders. Zero frame: the
    // window capsule IS the input bounds.
    <div className="flex h-screen flex-col justify-center overflow-hidden text-zinc-100">
      <m.div
        key={activationCount}
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
      </m.div>
    </div>
  );
}

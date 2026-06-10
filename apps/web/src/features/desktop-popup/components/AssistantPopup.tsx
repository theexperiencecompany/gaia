"use client";

import { Button } from "@heroui/button";
import { Cancel01Icon } from "@icons";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { useEffect, useState } from "react";
import { useUser } from "@/features/auth/hooks/useUser";
import { useElectron } from "@/hooks/useElectron";
import { useChatStoreSync } from "@/stores/chatStore";
import {
  AGENT_STATE_HINTS,
  POPUP_EASE,
  POPUP_TRANSITION_SECONDS,
} from "../constants";
import { usePopupVoice } from "../hooks/usePopupVoice";
import PopupComposer from "./PopupComposer";
import PopupFeed from "./PopupFeed";
import PopupOrb from "./PopupOrb";

/**
 * Siri-style assistant panel rendered inside the Electron popup window.
 *
 * The window itself provides the glass (macOS vibrancy); this component
 * provides the content and the entrance/exit choreography, driven by
 * `popup-activate` / `popup-deactivate` IPC events from the main process.
 */
export default function AssistantPopup() {
  const { dismissPopup, onPopupActivate, onPopupDeactivate } = useElectron();
  const { agentState, activate, deactivate } = usePopupVoice();
  const [visible, setVisible] = useState(false);
  const user = useUser();
  const isAuthenticated = Boolean(user?.email);

  useChatStoreSync();

  // Outside Electron (browser dev), show the panel immediately.
  useEffect(() => {
    if (typeof window !== "undefined" && !("api" in window)) {
      setVisible(true);
    }
  }, []);

  useEffect(() => {
    const offActivate = onPopupActivate(() => {
      setVisible(true);
      activate();
    });
    const offDeactivate = onPopupDeactivate(() => {
      setVisible(false);
      deactivate();
    });
    return () => {
      offActivate();
      offDeactivate();
    };
  }, [onPopupActivate, onPopupDeactivate, activate, deactivate]);

  useEffect(() => {
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") dismissPopup();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [dismissPopup]);

  return (
    <div className="h-screen overflow-hidden text-zinc-100">
      <AnimatePresence>
        {visible && (
          <m.div
            className="flex h-full flex-col"
            initial={{ opacity: 0, scale: 0.96, y: -10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: -6 }}
            transition={{
              duration: POPUP_TRANSITION_SECONDS,
              ease: POPUP_EASE,
            }}
          >
            <header className="relative flex flex-col items-center pt-6 pb-2">
              <Button
                isIconOnly
                size="sm"
                radius="full"
                variant="light"
                className="absolute top-2 right-2 text-zinc-500 hover:text-zinc-300"
                onPress={dismissPopup}
                aria-label="Dismiss"
              >
                <Cancel01Icon className="size-4" />
              </Button>
              <PopupOrb state={agentState} />
              <p className="pt-2 text-xs text-zinc-400">
                {isAuthenticated
                  ? AGENT_STATE_HINTS[agentState]
                  : "Sign in from the GAIA window to start chatting"}
              </p>
            </header>

            {isAuthenticated ? (
              <>
                <PopupFeed />
                <PopupComposer active={visible} />
              </>
            ) : (
              <div className="flex-1" />
            )}
          </m.div>
        )}
      </AnimatePresence>
    </div>
  );
}

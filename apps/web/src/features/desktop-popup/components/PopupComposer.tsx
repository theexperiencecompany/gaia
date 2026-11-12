"use client";

import { InputGroup, TextField } from "@heroui/react";
import { Cancel01Icon } from "@icons";
import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import { inputVariants } from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { useConversation } from "@/features/chat/hooks/useConversation";
import { sendMessage } from "@/features/chat/stream/sendMessage";
import { useElectron } from "@/hooks/useElectron";
import { useIsInitialResponseStreaming } from "@/stores/streamStore";
import { usePopupDismissGuard } from "../hooks/usePopupEscapeDismiss";
import type { PopupAgentState } from "../hooks/usePopupVoice";
import PopupOrb from "./PopupOrb";

interface PopupComposerProps {
  /** Focus the input when the popup activates. */
  active: boolean;
  /** Drives the orb inside the input. */
  agentState: PopupAgentState;
  /** Disable input (e.g. unauthenticated). */
  disabled?: boolean;
}

/**
 * The Siri-style pill: the window's liquid glass is the field itself —
 * glowing orb on the left, the shared send/stop button on the right.
 * Sends through the real chat-stream pipeline.
 */
export default function PopupComposer({
  active,
  agentState,
  disabled = false,
}: Readonly<PopupComposerProps>) {
  const [text, setText] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const isStreaming = useIsInitialResponseStreaming();
  const { dismissPopup } = useElectron();
  const dismissIfIdle = usePopupDismissGuard();
  const { convoMessages } = useConversation();
  const messageCount = convoMessages?.length ?? 0;
  const hasContent = text.trim().length > 0 && !disabled;

  useEffect(() => {
    if (active && !disabled) inputRef.current?.focus();
  }, [active, disabled]);

  // Refocus on every new message so the user can keep typing without
  // reaching for the mouse.
  useEffect(() => {
    if (messageCount > 0 && !disabled) inputRef.current?.focus();
  }, [messageCount, disabled]);

  const handleSend = () => {
    if (!hasContent || isStreaming) return;
    const content = text;
    setText("");
    // No client-side paid-only pre-check here: a free user's send gets a 402
    // from chat-stream, and `PopupPaywallNotice` renders that block in the
    // feed window (this pill has no room for it). See sync.ts.
    sendMessage(content).catch((error) => {
      console.error("Popup send failed", error);
    });
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.nativeEvent.isComposing) return;
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSend();
    }
    // The field swallows Escape (react-aria clear behavior) before the
    // window-level handler sees it — apply the same idle-guarded dismiss here.
    if (event.key === "Escape") {
      dismissIfIdle();
    }
  };

  return (
    <div data-popup-composer>
      <TextField
        className={inputVariants({ size: "sm" })}
        value={text}
        onChange={setText}
        isDisabled={disabled}
      >
        <InputGroup
          className="
            bg-transparent shadow-none border-none outline-none ring-0 py-0 pl-0.5 pr-2
          "
        >
          <InputGroup.Prefix>
            {/* Canvas is larger than the visible sphere (glow padding) — the
                negative margins keep the optical size in line with the send
                button while letting the glow breathe. */}
            <PopupOrb state={agentState} className="-m-3 size-16 shrink-0" />
          </InputGroup.Prefix>
          <InputGroup.Input
            ref={inputRef}
            onKeyDown={handleKeyDown}
            placeholder={
              disabled ? "Sign in from the GAIA window to chat" : "Ask GAIA…"
            }
            className="px-1.5 text-sm text-zinc-100 outline-none placeholder:text-zinc-400"
          />
          <InputGroup.Suffix>
            {/* The pill's capsule IS the window shape — a corner-overhanging
                X would always be sliced by its curve, so the close button
                lives inside the right end instead. */}
            <GaiaButton
              shape="pill"
              isIconOnly
              size="sm"
              variant="ghost"
              onPress={dismissPopup}
              aria-label="Close"
              tone="faint"
              className="h-6 min-h-6 w-6 max-w-6 min-w-6 shrink-0"
            >
              <Cancel01Icon className="size-3.5" />
            </GaiaButton>
          </InputGroup.Suffix>
        </InputGroup>
      </TextField>
    </div>
  );
}

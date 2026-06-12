"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { Cancel01Icon } from "@icons";
import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import { useConversation } from "@/features/chat/hooks/useConversation";
import { useElectron } from "@/hooks/useElectron";
import { useSendMessage } from "@/hooks/useSendMessage";
import { useIsMainResponseStreaming } from "@/stores/loadingStore";
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
}: PopupComposerProps) {
  const [text, setText] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const sendMessage = useSendMessage();
  const isStreaming = useIsMainResponseStreaming();
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
    sendMessage(content);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
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
      <Input
        ref={inputRef}
        value={text}
        onValueChange={setText}
        onKeyDown={handleKeyDown}
        isDisabled={disabled}
        placeholder={
          disabled ? "Sign in from the GAIA window to chat" : "Ask GAIA…"
        }
        radius="full"
        size="lg"
        startContent={
          // Canvas is larger than the visible sphere (glow padding) — the
          // negative margins keep the optical size in line with the send
          // button while letting the glow breathe.
          <PopupOrb state={agentState} className="-m-3 size-16 shrink-0" />
        }
        endContent={
          // The pill's capsule IS the window shape — a corner-overhanging
          // X would always be sliced by its curve, so the close button
          // lives inside the right end instead.
          <Button
            isIconOnly
            size="sm"
            radius="full"
            variant="light"
            onPress={dismissPopup}
            aria-label="Close"
            className="h-6 min-h-6 w-6 max-w-6 min-w-6 shrink-0 text-zinc-500 hover:text-zinc-200"
          >
            <Cancel01Icon className="size-3.5" />
          </Button>
        }
        classNames={{
          // Fully transparent: the window's liquid glass IS the field's
          // background — no overlay tints, no borders, no focus ring.
          // No send button — Enter sends; the orb carries the state.
          inputWrapper:
            "bg-transparent shadow-none border-none outline-none ring-0 py-0 pl-0.5 pr-2 data-[hover=true]:bg-transparent group-data-[focus=true]:bg-transparent group-data-[focus-visible=true]:ring-0 group-data-[focus-visible=true]:ring-offset-0",
          input:
            "px-1.5 text-sm text-zinc-100 outline-none placeholder:text-zinc-400",
        }}
      />
    </div>
  );
}

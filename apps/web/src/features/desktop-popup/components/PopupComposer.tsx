"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { ArrowUp02Icon } from "@icons";
import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import { useSendMessage } from "@/hooks/useSendMessage";
import { useIsMainResponseStreaming } from "@/stores/loadingStore";
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
 * The Siri-style top pill: its own glass surface with the glowing orb on
 * the left and the send button on the right, both inside the field.
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
  const canSend = text.trim().length > 0 && !isStreaming && !disabled;

  useEffect(() => {
    if (active && !disabled) inputRef.current?.focus();
  }, [active, disabled]);

  const handleSend = () => {
    if (!canSend) return;
    const content = text;
    setText("");
    sendMessage(content);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSend();
    }
  };

  return (
    <Input
      ref={inputRef}
      value={text}
      onValueChange={setText}
      onKeyDown={handleKeyDown}
      isDisabled={disabled}
      placeholder="Ask GAIA…"
      radius="full"
      size="lg"
      startContent={
        // Canvas is larger than the visible sphere (glow padding) — the
        // negative margins keep the optical size in line with the send
        // button while letting the glow breathe.
        <PopupOrb state={agentState} className="-m-2 size-13 shrink-0" />
      }
      endContent={
        <Button
          isIconOnly
          size="sm"
          radius="full"
          color="primary"
          isDisabled={!canSend}
          onPress={handleSend}
          aria-label="Send message"
        >
          <ArrowUp02Icon className="size-4" color="black" />
        </Button>
      }
      classNames={{
        inputWrapper:
          "bg-white/10 backdrop-blur-xl py-1.5 pl-2 pr-2 data-[hover=true]:bg-white/15 group-data-[focus=true]:bg-white/15",
        input: "px-2 text-sm text-zinc-100 placeholder:text-zinc-400",
      }}
    />
  );
}

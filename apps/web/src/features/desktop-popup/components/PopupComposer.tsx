"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { ArrowUp02Icon } from "@icons";
import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import { useSendMessage } from "@/hooks/useSendMessage";
import { useIsMainResponseStreaming } from "@/stores/loadingStore";

interface PopupComposerProps {
  /** Focus the input when the popup activates. */
  active: boolean;
}

/**
 * Compact text composer — stands in for speech until voice mode lands,
 * and remains the keyboard fallback afterwards. Sends through the real
 * chat-stream pipeline.
 */
export default function PopupComposer({ active }: PopupComposerProps) {
  const [text, setText] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const sendMessage = useSendMessage();
  const isStreaming = useIsMainResponseStreaming();
  const canSend = text.trim().length > 0 && !isStreaming;

  useEffect(() => {
    if (active) inputRef.current?.focus();
  }, [active]);

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
    <div className="flex items-center gap-2 p-3">
      <Input
        ref={inputRef}
        value={text}
        onValueChange={setText}
        onKeyDown={handleKeyDown}
        placeholder="Ask GAIA…"
        radius="full"
        classNames={{
          inputWrapper:
            "bg-zinc-800/60 backdrop-blur-xl data-[hover=true]:bg-zinc-800/80 group-data-[focus=true]:bg-zinc-800/80",
          input: "text-sm text-zinc-100 placeholder:text-zinc-500",
        }}
      />
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
    </div>
  );
}

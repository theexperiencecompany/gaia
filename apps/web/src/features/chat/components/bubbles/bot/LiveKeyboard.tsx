"use client";

import { Button } from "@heroui/button";
import { KeyboardIcon } from "@icons";
import type { LiveBrowser } from "@/features/browser/hooks/useLiveBrowser";

interface LiveKeyboardProps {
  live: Pick<LiveBrowser, "keyboardRef" | "openKeyboard">;
  className?: string;
}

/**
 * Raises a phone's soft keyboard over the live browser. The canvas cannot take
 * text input, so focus goes to an off-screen input whose edits useLiveInput
 * forwards to the page.
 */
export function LiveKeyboard({ live, className }: LiveKeyboardProps) {
  return (
    <>
      {/* A raw input on purpose: it is never seen, only focused, and HeroUI's
          Input wraps it in visible chrome. 16px stops iOS zooming on focus. */}
      <input
        ref={live.keyboardRef}
        type="text"
        autoComplete="off"
        autoCapitalize="off"
        autoCorrect="off"
        spellCheck={false}
        aria-label="Type into the live browser"
        className="fixed -left-[1000px] top-0 size-px text-[16px] opacity-0"
      />
      <Button
        size="sm"
        variant="flat"
        radius="full"
        className={className}
        startContent={<KeyboardIcon className="size-4" />}
        onPress={live.openKeyboard}
      >
        Keyboard
      </Button>
    </>
  );
}

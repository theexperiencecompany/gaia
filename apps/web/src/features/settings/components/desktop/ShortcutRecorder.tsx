"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

interface ShortcutRecorderProps {
  /** Electron accelerator string, e.g. "CommandOrControl+Shift+G". */
  value: string;
  /** Called with the recorded accelerator; resolves false to revert. */
  onRecord: (accelerator: string) => Promise<boolean>;
}

const IS_MAC =
  typeof navigator !== "undefined" && navigator.platform.includes("Mac");

/** Display symbol for each accelerator token. */
const TOKEN_SYMBOLS: Record<string, string> = {
  CommandOrControl: IS_MAC ? "⌘" : "Ctrl",
  Command: "⌘",
  Cmd: "⌘",
  Control: IS_MAC ? "⌃" : "Ctrl",
  Ctrl: IS_MAC ? "⌃" : "Ctrl",
  Alt: IS_MAC ? "⌥" : "Alt",
  Option: "⌥",
  Shift: IS_MAC ? "⇧" : "Shift",
  Super: IS_MAC ? "⌘" : "Win",
  Meta: IS_MAC ? "⌘" : "Win",
  Space: "␣",
  Up: "↑",
  Down: "↓",
  Left: "←",
  Right: "→",
  Return: "↩",
  Enter: "↩",
  Backspace: "⌫",
  Delete: "⌦",
  Escape: "⎋",
};

/** Map a KeyboardEvent to the Electron accelerator key token, or null. */
function eventKeyToken(event: KeyboardEvent): string | null {
  const { code } = event;
  if (/^Key[A-Z]$/.test(code)) return code.slice(3);
  if (/^Digit[0-9]$/.test(code)) return code.slice(5);
  if (/^F([1-9]|1[0-9]|2[0-4])$/.test(code)) return code;
  const named: Record<string, string> = {
    Space: "Space",
    Tab: "Tab",
    Enter: "Return",
    Backspace: "Backspace",
    Delete: "Delete",
    ArrowUp: "Up",
    ArrowDown: "Down",
    ArrowLeft: "Left",
    ArrowRight: "Right",
    Home: "Home",
    End: "End",
    PageUp: "PageUp",
    PageDown: "PageDown",
  };
  return named[code] ?? null;
}

function eventModifiers(event: KeyboardEvent): string[] {
  const modifiers: string[] = [];
  // Record the primary modifier as CommandOrControl so the shortcut keeps
  // working if the settings file ever moves between platforms.
  if (IS_MAC ? event.metaKey : event.ctrlKey)
    modifiers.push("CommandOrControl");
  if (IS_MAC && event.ctrlKey) modifiers.push("Control");
  if (event.altKey) modifiers.push("Alt");
  if (event.shiftKey) modifiers.push("Shift");
  return modifiers;
}

function ShortcutKeycaps({ accelerator }: { accelerator: string }) {
  return (
    <span className="flex items-center gap-1">
      {accelerator.split("+").map((token) => (
        <kbd
          key={token}
          className="flex h-6 min-w-6 items-center justify-center rounded-md bg-zinc-700/80 px-1.5 text-xs font-medium text-zinc-200"
        >
          {TOKEN_SYMBOLS[token] ?? token}
        </kbd>
      ))}
    </span>
  );
}

/**
 * Industry-standard shortcut recorder: click to arm, press the combo,
 * Esc cancels. Shows the live combo while keys are held.
 */
export function ShortcutRecorder({ value, onRecord }: ShortcutRecorderProps) {
  const [recording, setRecording] = useState(false);
  const [heldPreview, setHeldPreview] = useState<string | null>(null);
  const containerRef = useRef<HTMLButtonElement>(null);

  const stopRecording = useCallback(() => {
    setRecording(false);
    setHeldPreview(null);
  }, []);

  useEffect(() => {
    if (!recording) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      event.preventDefault();
      event.stopPropagation();

      if (event.code === "Escape" && eventModifiers(event).length === 0) {
        stopRecording();
        return;
      }

      const modifiers = eventModifiers(event);
      const key = eventKeyToken(event);

      if (!key) {
        // Only modifiers held so far — show them as a live preview.
        setHeldPreview(modifiers.length > 0 ? modifiers.join("+") : null);
        return;
      }
      if (modifiers.length === 0) {
        setHeldPreview(key);
        return;
      }

      const accelerator = [...modifiers, key].join("+");
      stopRecording();
      void onRecord(accelerator);
    };

    const handleKeyUp = () => setHeldPreview(null);

    window.addEventListener("keydown", handleKeyDown, true);
    window.addEventListener("keyup", handleKeyUp, true);
    return () => {
      window.removeEventListener("keydown", handleKeyDown, true);
      window.removeEventListener("keyup", handleKeyUp, true);
    };
  }, [recording, onRecord, stopRecording]);

  return (
    <button
      ref={containerRef}
      type="button"
      onClick={() => (recording ? stopRecording() : setRecording(true))}
      onBlur={stopRecording}
      className={cn(
        "flex h-9 min-w-36 items-center justify-center rounded-xl px-3 transition-colors",
        recording
          ? "bg-primary/15 text-primary"
          : "bg-zinc-800 hover:bg-zinc-700/80",
      )}
    >
      {recording ? (
        heldPreview ? (
          <ShortcutKeycaps accelerator={heldPreview} />
        ) : (
          <span className="text-xs text-primary">
            Type shortcut, Esc to cancel
          </span>
        )
      ) : (
        <ShortcutKeycaps accelerator={value} />
      )}
    </button>
  );
}

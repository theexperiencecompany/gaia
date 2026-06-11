"use client";

import type { KbdKey } from "@heroui/kbd";
import { Kbd } from "@heroui/kbd";
import { useCallback, useEffect, useState } from "react";
import { cn } from "@/lib/utils";

interface ShortcutRecorderProps {
  /** Electron accelerator string, e.g. "CommandOrControl+Shift+G". */
  value: string;
  /** Called with the recorded accelerator; resolves false to revert. */
  onRecord: (accelerator: string) => Promise<boolean>;
}

const IS_MAC =
  typeof navigator !== "undefined" && navigator.platform.includes("Mac");

/** Accelerator modifier token → HeroUI Kbd key. */
const MODIFIER_KBD_KEYS: Record<string, KbdKey> = {
  CommandOrControl: IS_MAC ? "command" : "ctrl",
  Command: "command",
  Cmd: "command",
  Control: "ctrl",
  Ctrl: "ctrl",
  Alt: "option",
  Option: "option",
  Shift: "shift",
  Super: "command",
  Meta: "command",
};

/** Named (non-modifier) accelerator keys that Kbd renders as symbols. */
const NAMED_KBD_KEYS: Record<string, KbdKey> = {
  Space: "space",
  Tab: "tab",
  Return: "enter",
  Enter: "enter",
  Backspace: "delete",
  Delete: "delete",
  Escape: "escape",
  Up: "up",
  Down: "down",
  Left: "left",
  Right: "right",
  Home: "home",
  End: "end",
  PageUp: "pageup",
  PageDown: "pagedown",
};

/** Split an accelerator into Kbd modifier keys + the literal key label. */
function acceleratorToKbd(accelerator: string): {
  keys: KbdKey[];
  label: string;
} {
  const keys: KbdKey[] = [];
  let label = "";
  for (const token of accelerator.split("+")) {
    const modifier = MODIFIER_KBD_KEYS[token];
    if (modifier) {
      if (!keys.includes(modifier)) keys.push(modifier);
      continue;
    }
    const named = NAMED_KBD_KEYS[token];
    if (named) {
      keys.push(named);
      continue;
    }
    label = token;
  }
  return { keys, label };
}

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

function ShortcutKbd({ accelerator }: { accelerator: string }) {
  const { keys, label } = acceleratorToKbd(accelerator);
  return (
    <Kbd keys={keys} classNames={{ base: "bg-zinc-700/80 shadow-none" }}>
      {label}
    </Kbd>
  );
}

/**
 * Industry-standard shortcut recorder: click to arm, press the combo,
 * Esc cancels. Shows the live combo while keys are held.
 */
export function ShortcutRecorder({ value, onRecord }: ShortcutRecorderProps) {
  const [recording, setRecording] = useState(false);
  const [heldPreview, setHeldPreview] = useState<string | null>(null);

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
          <ShortcutKbd accelerator={heldPreview} />
        ) : (
          <span className="text-xs text-primary">
            Type shortcut, Esc to cancel
          </span>
        )
      ) : (
        <ShortcutKbd accelerator={value} />
      )}
    </button>
  );
}

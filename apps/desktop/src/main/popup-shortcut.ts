/**
 * Global shortcut that summons the assistant popup — user-configurable.
 *
 * @module popup-shortcut
 */

import type { DesktopShortcutUpdateResult } from "@gaia/shared/desktop-tools";
import { globalShortcut } from "electron";
import { getDesktopSettings, updateDesktopSettings } from "./settings";
import { toggleAssistantPopup } from "./windows/assistant-popup";

const MODIFIERS = new Set([
  "CommandOrControl",
  "Command",
  "Control",
  "Cmd",
  "Ctrl",
  "Alt",
  "Option",
  "Shift",
  "Super",
  "Meta",
]);

const NAMED_KEYS = new Set([
  "Space",
  "Tab",
  "Backspace",
  "Delete",
  "Return",
  "Enter",
  "Escape",
  "Up",
  "Down",
  "Left",
  "Right",
  "Home",
  "End",
  "PageUp",
  "PageDown",
]);

/** Accelerator must be one or more modifiers + exactly one real key. */
function isValidAccelerator(accelerator: string): boolean {
  const parts = accelerator.split("+");
  if (parts.length < 2) return false;
  const key = parts[parts.length - 1];
  const modifiers = parts.slice(0, -1);
  if (!modifiers.every((part) => MODIFIERS.has(part))) return false;
  return (
    /^[A-Z0-9]$/.test(key) ||
    /^F([1-9]|1[0-9]|2[0-4])$/.test(key) ||
    NAMED_KEYS.has(key)
  );
}

let registeredShortcut: string | null = null;

/** Register the persisted popup shortcut at startup. */
export function registerPopupShortcut(): void {
  const { popupShortcut } = getDesktopSettings();
  if (globalShortcut.register(popupShortcut, toggleAssistantPopup)) {
    registeredShortcut = popupShortcut;
  } else {
    console.warn("[Main] Failed to register shortcut:", popupShortcut);
  }
}

/**
 * Swap the popup shortcut: unregister the old one, try the new one, and
 * roll back if the OS refuses it (e.g. taken by another app).
 */
export function updatePopupShortcut(
  accelerator: string,
): DesktopShortcutUpdateResult {
  const current = registeredShortcut;

  if (!isValidAccelerator(accelerator)) {
    return {
      ok: false,
      // Report only the shortcut actually registered with the OS — never a
      // persisted value that may not be active — so the settings UI can't
      // desync from real OS state.
      shortcut: current ?? "",
      error: "Shortcut must combine at least one modifier with a key",
    };
  }

  if (current) globalShortcut.unregister(current);

  if (globalShortcut.register(accelerator, toggleAssistantPopup)) {
    registeredShortcut = accelerator;
    updateDesktopSettings({ popupShortcut: accelerator });
    console.log("[Main] Popup shortcut updated:", accelerator);
    return { ok: true, shortcut: accelerator, error: null };
  }

  // Roll back — the previous shortcut kept working before this call.
  registeredShortcut = null;
  if (current && globalShortcut.register(current, toggleAssistantPopup)) {
    registeredShortcut = current;
  }
  return {
    ok: false,
    // Reflect what is genuinely registered after rollback: the previous
    // shortcut if it was reclaimed, otherwise nothing.
    shortcut: registeredShortcut ?? "",
    error: "That shortcut is unavailable (it may be used by another app)",
  };
}

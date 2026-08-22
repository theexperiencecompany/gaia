"use client";

import { Kbd } from "@heroui/kbd";
import { Fragment } from "react";

/**
 * Parse keys string into display-friendly array
 * Examples:
 *   "g>d" -> ["G", "D"]
 *   "shift+/" -> ["?"]
 *   "c" -> ["C"]
 */
function parseDisplayKeys(keys: string): string[] {
  // Handle sequential keys (g>d)
  if (keys.includes(">")) {
    return keys.split(">").map((k) => k.toUpperCase());
  }

  // Handle modifier combinations
  if (keys.includes("+")) {
    // Special case: shift+/ displays as ?
    if (keys === "shift+/") return ["?"];

    return keys.split("+").map((k) => {
      const lower = k.toLowerCase();
      if (lower === "mod") return "⌘/Ctrl";
      if (lower === "shift") return "Shift";
      if (lower === "alt") return "Alt";
      if (lower === "ctrl") return "Ctrl";
      if (lower === "meta") return "⌘";
      return k.toUpperCase();
    });
  }

  // Single key
  return [keys.toUpperCase()];
}

/**
 * Render shortcut keys as Kbd elements with "then" separator
 */
export function ShortcutKeysDisplay({
  keys,
  size = "sm",
}: {
  keys: string;
  size?: "sm" | "md";
}) {
  const displayKeys = parseDisplayKeys(keys);
  const kbdClass = `${size === "sm" ? "text-[10px]" : ""} rounded-sm`;

  if (displayKeys.length === 1)
    return <Kbd className={kbdClass}>{displayKeys[0]}</Kbd>;

  return (
    <span className="flex items-center gap-1">
      {displayKeys.map((key, i) => (
        <Fragment key={key}>
          <Kbd className={kbdClass}>{key}</Kbd>
          {i < displayKeys.length - 1 && (
            <span
              className={`text-zinc-400 ${size === "sm" ? "text-xs" : "text-sm"}`}
            >
              then
            </span>
          )}
        </Fragment>
      ))}
    </span>
  );
}

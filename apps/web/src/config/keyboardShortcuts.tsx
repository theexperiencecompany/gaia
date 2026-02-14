"use client";

import { Kbd } from "@heroui/kbd";
import {
  BubbleChatAddIcon,
  Calendar03Icon,
  CheckListIcon,
  ConnectIcon,
  DashboardSquare02Icon,
  MessageMultiple02Icon,
  Target02Icon,
  ZapIcon,
} from "@icons";
import { Fragment } from "react";

/**
 * Keyboard shortcut definition
 */
export interface KeyboardShortcut {
  id: string;
  /** Key combo for react-hotkeys-hook (e.g., "c", "g>w" for sequences) */
  keys: string;
  /** Description of what the shortcut does */
  description: string;
  /** Category for grouping in cheat sheet */
  category: "create" | "navigation" | "general";
  /** Optional path for navigation shortcuts */
  path?: string;
  /** Optional icon for display */
  icon?: React.ReactNode;
}

/**
 * Parse keys string into display-friendly array
 * Examples:
 *   "g>d" -> ["G", "D"]
 *   "shift+/" -> ["?"]
 *   "c" -> ["C"]
 */
export function parseDisplayKeys(keys: string): string[] {
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
 * All keyboard shortcuts in the application
 */
export const KEYBOARD_SHORTCUTS: KeyboardShortcut[] = [
  // Create Actions - Page specific
  {
    id: "create_chat",
    keys: "c",
    description: "New Chat",
    category: "create",
    icon: <BubbleChatAddIcon width={16} height={16} />,
  },
  {
    id: "create_todo",
    keys: "c",
    description: "New Todo (on Todos page)",
    category: "create",
    icon: <CheckListIcon width={16} height={16} />,
  },
  {
    id: "create_goal",
    keys: "c",
    description: "New Goal (on Goals page)",
    category: "create",
    icon: <Target02Icon width={16} height={16} />,
  },
  {
    id: "create_workflow",
    keys: "c",
    description: "New Workflow (on Workflows page)",
    category: "create",
    icon: <ZapIcon width={16} height={16} />,
  },
  {
    id: "create_event",
    keys: "c",
    description: "New Event (on Calendar page)",
    category: "create",
    icon: <Calendar03Icon width={16} height={16} />,
  },
  {
    id: "create_integration",
    keys: "c",
    description: "New Integration (on Integrations page)",
    category: "create",
    icon: <ConnectIcon width={16} height={16} />,
  },

  // Navigation shortcuts (G -> X sequences)
  {
    id: "goto_dashboard",
    keys: "g>d",
    description: "Go to Dashboard",
    category: "navigation",
    path: "/dashboard",
    icon: <DashboardSquare02Icon width={16} height={16} />,
  },
  {
    id: "goto_calendar",
    keys: "g>c",
    description: "Go to Calendar",
    category: "navigation",
    path: "/calendar",
    icon: <Calendar03Icon width={16} height={16} />,
  },
  {
    id: "goto_todos",
    keys: "g>t",
    description: "Go to Todos",
    category: "navigation",
    path: "/todos",
    icon: <CheckListIcon width={16} height={16} />,
  },
  {
    id: "goto_goals",
    keys: "g>o",
    description: "Go to Goals",
    category: "navigation",
    path: "/goals",
    icon: <Target02Icon width={16} height={16} />,
  },
  {
    id: "goto_workflows",
    keys: "g>w",
    description: "Go to Workflows",
    category: "navigation",
    path: "/workflows",
    icon: <ZapIcon width={16} height={16} />,
  },
  {
    id: "goto_chats",
    keys: "g>h",
    description: "Go to Chats",
    category: "navigation",
    path: "/c",
    icon: <MessageMultiple02Icon width={16} height={16} />,
  },
  {
    id: "goto_integrations",
    keys: "g>i",
    description: "Go to Integrations",
    category: "navigation",
    path: "/integrations",
    icon: <ConnectIcon width={16} height={16} />,
  },

  // General shortcuts
  {
    id: "shortcuts_menu",
    keys: "?",
    description: "Show keyboard shortcuts",
    category: "general",
  },
];

/**
 * Get shortcuts by category
 */
export const getShortcutsByCategory = (
  category: KeyboardShortcut["category"],
) => KEYBOARD_SHORTCUTS.filter((s) => s.category === category);

/**
 * Get navigation shortcut for sidebar tooltips
 */
export const getNavigationShortcut = (path: string) =>
  KEYBOARD_SHORTCUTS.find(
    (s) => s.path === path && s.category === "navigation",
  );

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

/**
 * Headless slash-command utilities — UI-agnostic.
 *
 * Extracted and unified from:
 *  - web: apps/web/src/features/chat/hooks/useSlashCommandDropdownState.ts
 *    (filterMatchesByCategory, buildCategories, clampSelection,
 *     handleSlashCommandKey, dropdown positioning, update detection)
 *  - web: apps/web/src/features/chat/hooks/useSlashCommands.ts
 *    (detectSlashCommand, getSlashCommandSuggestions)
 *  - mobile: apps/mobile/src/features/chat/components/composer/composer.tsx
 *    (isCommandMode via trimmed startsWith slash,
 *     commandQuery via slice lowercasing,
 *     matchingCommands prefix filter)
 *
 * Headless guarantee: pure functions only, no browser globals,
 * no platform view primitives, no view-markup. Works on web, mobile,
 * desktop, and node.
 */

// ---------------------------------------------------------------------------
// Types (minimal, headless)
// ---------------------------------------------------------------------------

export interface SlashTool {
  name: string;
  category: string;
  display_name?: string;
  icon_url?: string;
  locked?: boolean;
}

export interface EnhancedToolInfo {
  isLocked?: boolean;
  displayName?: string;
  iconUrl?: string;
  name?: string;
  category?: string;
}

export interface SlashCommandMatch {
  tool: SlashTool;
  enhancedTool?: EnhancedToolInfo;
  matchedText: string;
}

export interface SlashDetection {
  isSlashCommand: boolean;
  query: string;
  matches?: SlashCommandMatch[];
  commandStart: number;
  commandEnd: number;
}

// ---------------------------------------------------------------------------
// Mobile-origin helpers — isCommandMode / getCommandQuery
// ---------------------------------------------------------------------------

/**
 * Headless equivalent of mobile isCommandMode.
 * Mobile checks trimmed.startsWith("/") where trimmed is message.trim().
 */
export function isCommandMode(text: string): boolean {
  return text.trim().startsWith("/");
}

/**
 * Headless equivalent of mobile commandQuery.
 * Returns trimmed.slice(1).toLowerCase() or "" when not in command mode.
 */
export function getCommandQuery(text: string): string {
  const trimmed = text.trim();
  if (!trimmed.startsWith("/")) return "";
  return trimmed.slice(1).toLowerCase();
}

/**
 * Filter a simple string command list (mobile DEFAULT_COMMANDS style)
 * by a query prefix — case-insensitive.
 */
export function getMatchingCommands(
  query: string,
  commands: string[],
): string[] {
  const q = query.toLowerCase();
  if (!q) return [...commands];
  return commands.filter((c) => c.toLowerCase().startsWith(q));
}

// ---------------------------------------------------------------------------
// Web-origin pure helpers — category / selection
// ---------------------------------------------------------------------------

/** Matches of one category, or all of them for the "all" tab. */
export function filterMatchesByCategory(
  category: string,
  matches: SlashCommandMatch[],
): SlashCommandMatch[] {
  if (category === "all") return matches;
  return matches.filter((match) => match.tool.category === category);
}

/**
 * Every tool category becomes a top-level tab.
 * Mirrors web buildCategories.
 */
export function buildCategories(matches: SlashCommandMatch[]): string[] {
  const uniqueCategories = Array.from(
    new Set(matches.map((match) => match.tool.category)),
  );
  return ["all", ...uniqueCategories.toSorted((a, b) => a.localeCompare(b))];
}

/**
 * Move selectedIndex by delta within unlocked-row space, clamped to
 * [0, unlockedCount - 1]. Mirrors web clampSelection.
 */
export function clampSelection(
  delta: 1 | -1,
  currentIndex: number,
  unlockedCount: number,
): number {
  if (unlockedCount <= 0) return currentIndex;
  return Math.min(Math.max(currentIndex + delta, 0), unlockedCount - 1);
}

/**
 * Get the next category index when navigating left/right, clamped.
 */
export function getNextCategoryIndex(
  currentCategory: string,
  categories: string[],
  direction: -1 | 1,
): number {
  const currentIndex = categories.indexOf(currentCategory);
  if (currentIndex === -1) return 0;
  return Math.min(Math.max(currentIndex + direction, 0), categories.length - 1);
}

/**
 * Resolve the currently selected match from an unlocked-only index.
 */
export function getSelectedMatch(
  matches: SlashCommandMatch[],
  selectedCategory: string,
  selectedIndex: number,
): SlashCommandMatch | undefined {
  const unlockedMatches = filterMatchesByCategory(
    selectedCategory,
    matches,
  ).filter((match) => !match.enhancedTool?.isLocked);
  return unlockedMatches[selectedIndex];
}

/**
 * Count unlocked matches in a given category scope.
 */
export function getUnlockedCount(
  matches: SlashCommandMatch[],
  selectedCategory: string,
): number {
  return filterMatchesByCategory(selectedCategory, matches).filter(
    (m) => !m.enhancedTool?.isLocked,
  ).length;
}

// ---------------------------------------------------------------------------
// Detection — pure text to slash command, no view layer
// ---------------------------------------------------------------------------

/**
 * Check if a slash at lastSlashIndex is a valid command start.
 * Valid when at start or preceded by whitespace, and not followed by space.
 */
export function isValidSlashPosition(
  text: string,
  lastSlashIndex: number,
): boolean {
  if (lastSlashIndex < 0) return false;
  const charBeforeSlash = lastSlashIndex > 0 ? text[lastSlashIndex - 1] : " ";
  const isAtStartOrAfterWhitespace =
    lastSlashIndex === 0 || /\s/.test(charBeforeSlash);
  if (!isAtStartOrAfterWhitespace) return false;
  const textAfterSlash = text.substring(lastSlashIndex + 1);
  if (textAfterSlash.startsWith(" ")) return false;
  return true;
}

/**
 * Pure slash command detection — headless version of
 * useSlashCommands detectSlashCommand.
 *
 * Finds last "/" before cursorPosition, validates position,
 * and extracts query + command range.
 */
export function detectSlashCommand(
  text: string,
  cursorPosition: number,
): SlashDetection {
  const textBeforeCursor = text.substring(0, cursorPosition);
  const lastSlashIndex = textBeforeCursor.lastIndexOf("/");

  if (lastSlashIndex === -1) {
    return {
      isSlashCommand: false,
      query: "",
      commandStart: -1,
      commandEnd: -1,
    };
  }

  if (!isValidSlashPosition(text, lastSlashIndex)) {
    return {
      isSlashCommand: false,
      query: "",
      commandStart: -1,
      commandEnd: -1,
    };
  }

  const textAfterSlash = text.substring(lastSlashIndex + 1);
  const nextSlashIndex = textAfterSlash.indexOf("/");
  const commandEnd =
    nextSlashIndex === -1 ? text.length : lastSlashIndex + 1 + nextSlashIndex;

  if (cursorPosition > commandEnd) {
    return {
      isSlashCommand: false,
      query: "",
      commandStart: -1,
      commandEnd: -1,
    };
  }

  const query = text.substring(lastSlashIndex + 1, cursorPosition);

  return {
    isSlashCommand: true,
    query,
    commandStart: lastSlashIndex,
    commandEnd,
  };
}

/**
 * Headless key handling — pure state transition for the slash dropdown.
 * Mirrors web handleSlashCommandKey but without view event.
 */
export type SlashKey =
  | "ArrowUp"
  | "ArrowDown"
  | "ArrowLeft"
  | "ArrowRight"
  | "Enter"
  | "Tab"
  | "Escape"
  | string;

export interface SlashKeyContext {
  matches: SlashCommandMatch[];
  selectedCategory: string;
  categories: string[];
  selectedIndex: number;
}

export type SlashKeyResult =
  | { action: "navigateUp"; nextIndex: number }
  | { action: "navigateDown"; nextIndex: number }
  | { action: "nextCategory"; nextCategory: string }
  | { action: "select"; match: SlashCommandMatch | undefined }
  | { action: "close" }
  | { action: "none" };

export function handleSlashKey(
  key: SlashKey,
  ctx: SlashKeyContext,
): SlashKeyResult {
  switch (key) {
    case "ArrowUp": {
      const unlockedCount = getUnlockedCount(ctx.matches, ctx.selectedCategory);
      return {
        action: "navigateUp",
        nextIndex: clampSelection(-1, ctx.selectedIndex, unlockedCount),
      };
    }
    case "ArrowDown": {
      const unlockedCount = getUnlockedCount(ctx.matches, ctx.selectedCategory);
      return {
        action: "navigateDown",
        nextIndex: clampSelection(1, ctx.selectedIndex, unlockedCount),
      };
    }
    case "ArrowLeft":
    case "ArrowRight": {
      const step = key === "ArrowLeft" ? -1 : 1;
      const nextIndex = getNextCategoryIndex(
        ctx.selectedCategory,
        ctx.categories,
        step as -1 | 1,
      );
      const nextCategory = ctx.categories[nextIndex];
      if (nextCategory) {
        return { action: "nextCategory", nextCategory };
      }
      return { action: "none" };
    }
    case "Enter":
    case "Tab": {
      const selectedMatch = getSelectedMatch(
        ctx.matches,
        ctx.selectedCategory,
        ctx.selectedIndex,
      );
      return { action: "select", match: selectedMatch };
    }
    case "Escape":
      return { action: "close" };
    default:
      return { action: "none" };
  }
}

/**
 * Legacy adapter: minimal event-like object for drop-in migration.
 * Headless callers should prefer handleSlashKey.
 */
export function handleSlashCommandKey(
  e: { key: string; preventDefault?: () => void },
  ctx: SlashKeyContext & {
    navigateUp?: () => void;
    navigateDown?: () => void;
    selectCategory: (category: string) => void;
    onSelect: (match: SlashCommandMatch) => void;
    onClose: () => void;
  },
): boolean {
  const result = handleSlashKey(e.key, ctx);
  switch (result.action) {
    case "navigateUp":
      e.preventDefault?.();
      ctx.navigateUp?.();
      return true;
    case "navigateDown":
      e.preventDefault?.();
      ctx.navigateDown?.();
      return true;
    case "nextCategory":
      e.preventDefault?.();
      ctx.selectCategory(result.nextCategory);
      return true;
    case "select":
      e.preventDefault?.();
      if (result.match) ctx.onSelect(result.match);
      return true;
    case "close":
      e.preventDefault?.();
      ctx.onClose();
      return true;
    default:
      return false;
  }
}

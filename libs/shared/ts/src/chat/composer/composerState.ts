/**
 * Headless composer state — UI-agnostic.
 *
 * Extracted from:
 *  - web: apps/web/src/stores/composerStore.ts (zustand store)
 *  - web: apps/web/src/features/chat/hooks/useSlashCommandDropdownState.ts
 *         (slash dropdown state machine, open/close, cursor tracking)
 *  - mobile: apps/mobile/src/features/chat/components/composer/composer.tsx
 *           (isCommandMode, commandQuery, internalMessage handling)
 *
 * Headless guarantee: no browser globals, no view primitives, no view-markup.
 * Framework-agnostic controller via useComposerBase factory.
 * Works in vanilla JS, Zustand, or wrapped with React primitives.
 */

import { COMPOSER_CONSTANTS } from "./constants";
import {
  buildCategories,
  clampSelection,
  detectSlashCommand,
  getCommandQuery,
  getSelectedMatch,
  getUnlockedCount,
  handleSlashKey,
  isCommandMode,
  type SlashCommandMatch,
  type SlashKey,
} from "./slash";

// ---------------------------------------------------------------------------
// State shape — mirrors web SlashCommandDropdownState but view-free
// ---------------------------------------------------------------------------

export interface ComposerState {
  text: string;
  cursorPosition: number;
  isActive: boolean;
  matches: SlashCommandMatch[];
  selectedIndex: number;
  commandStart: number;
  commandEnd: number;
  selectedCategory: string;
  categories: string[];
  selectedCategoryIndex: number;
  openedViaButton: boolean;
}

export const INITIAL_COMPOSER_STATE: ComposerState = {
  text: "",
  cursorPosition: 0,
  isActive: false,
  matches: [],
  selectedIndex: 0,
  commandStart: -1,
  commandEnd: -1,
  selectedCategory: "all",
  categories: [],
  selectedCategoryIndex: 0,
  openedViaButton: false,
};

// ---------------------------------------------------------------------------
// Options / Return — headless controller
// ---------------------------------------------------------------------------

export interface UseComposerBaseOptions {
  initialText?: string;
  initialCursor?: number;
  getSuggestions?: (query: string) => SlashCommandMatch[];
  tools?: SlashCommandMatch[];
  onSelect?: (
    match: SlashCommandMatch,
    next: { text: string; cursor: number },
  ) => void;
}

export interface UseComposerBaseReturn {
  getState: () => ComposerState;
  state: ComposerState;
  isCommandMode: () => boolean;
  getCommandQuery: () => string;
  setText: (text: string, cursorPosition?: number) => void;
  setCursor: (position: number) => void;
  openViaButton: () => void;
  close: () => void;
  toggle: () => void;
  selectCategory: (category: string) => void;
  navigateUp: () => void;
  navigateDown: () => void;
  selectMatch: (
    match: SlashCommandMatch,
  ) => { text: string; cursor: number } | null;
  selectCurrent: () => {
    text: string;
    cursor: number;
    match: SlashCommandMatch;
  } | null;
  updateDetection: (text: string, cursorPosition: number) => void;
  handleKey: (key: SlashKey) => boolean;
  subscribe: (listener: (state: ComposerState) => void) => () => void;
  constants: typeof COMPOSER_CONSTANTS;
}

// ---------------------------------------------------------------------------
// Factory — headless, UI-agnostic
// ---------------------------------------------------------------------------

function resolveSuggestions(
  query: string,
  opts: UseComposerBaseOptions,
): SlashCommandMatch[] {
  if (opts.getSuggestions) return opts.getSuggestions(query);
  if (opts.tools) {
    const q = query.toLowerCase();
    if (!q) return [...opts.tools];
    return opts.tools.filter(
      (m) =>
        m.tool.name.toLowerCase().includes(q) ||
        m.tool.category.toLowerCase().includes(q) ||
        (m.tool.display_name?.toLowerCase().includes(q) ?? false),
    );
  }
  return [];
}

/**
 * Headless composer base controller.
 *
 * View-agnostic: no refs, no text-area element, no browser layout APIs.
 * Owns text -> detection -> matches -> selection state.
 *
 * Named useComposerBase to match shared contract expectation
 * (@gaia/shared/chat/composer exports useComposerBase), but it is a
 * plain factory so it works outside React. React wrappers can call it
 * inside useMemo and subscribe.
 */
export function useComposerBase(
  options: UseComposerBaseOptions = {},
): UseComposerBaseReturn {
  const opts = options;

  let state: ComposerState = {
    ...INITIAL_COMPOSER_STATE,
    text: opts.initialText ?? "",
    cursorPosition:
      opts.initialCursor ?? (opts.initialText ? opts.initialText.length : 0),
  };

  const listeners = new Set<(s: ComposerState) => void>();
  const emit = () => {
    for (const l of listeners) l(state);
  };
  const setState = (patch: Partial<ComposerState>) => {
    state = { ...state, ...patch };
    (api.state as ComposerState) = state;
    emit();
  };

  const applyDetection = (text: string, cursor: number): void => {
    const detection = detectSlashCommand(text, cursor);
    if (detection.isSlashCommand) {
      const suggestions = resolveSuggestions(detection.query, opts);
      if (suggestions.length > 0) {
        const categories = buildCategories(suggestions);
        setState({
          text,
          cursorPosition: cursor,
          isActive: true,
          matches: suggestions,
          selectedIndex: 0,
          commandStart: detection.commandStart,
          commandEnd: detection.commandEnd,
          selectedCategory: "all",
          categories,
          selectedCategoryIndex: 0,
          openedViaButton: false,
        });
        return;
      }
      setState({
        text,
        cursorPosition: cursor,
        isActive: false,
        matches: [],
        selectedIndex: 0,
        commandStart: detection.commandStart,
        commandEnd: detection.commandEnd,
      });
      return;
    }

    if (state.openedViaButton && state.isActive) {
      setState({ text, cursorPosition: cursor });
      return;
    }
    setState({
      text,
      cursorPosition: cursor,
      isActive: false,
      matches: state.openedViaButton ? state.matches : [],
      selectedIndex: 0,
      commandStart: -1,
      commandEnd: -1,
    });
  };

  const api: UseComposerBaseReturn = {
    getState: () => state,
    state: state as ComposerState,

    isCommandMode: () => isCommandMode(state.text),
    getCommandQuery: () => getCommandQuery(state.text),

    setText: (text: string, cursorPosition?: number) => {
      const cursor = cursorPosition ?? text.length;
      applyDetection(text, cursor);
    },

    setCursor: (position: number) => {
      const clamped = Math.max(0, Math.min(position, state.text.length));
      applyDetection(state.text, clamped);
    },

    updateDetection: (text: string, cursorPosition: number) => {
      applyDetection(text, cursorPosition);
    },

    openViaButton: () => {
      if (state.isActive && state.openedViaButton) {
        setState({
          isActive: false,
          openedViaButton: false,
        });
        return;
      }
      const allMatches = resolveSuggestions("", opts);
      const categories = buildCategories(allMatches);
      setState({
        isActive: true,
        matches: allMatches,
        selectedIndex: 0,
        commandStart: 0,
        commandEnd: 0,
        selectedCategory: "all",
        categories,
        selectedCategoryIndex: 0,
        openedViaButton: true,
      });
    },

    close: () => {
      setState({ isActive: false, openedViaButton: false });
    },

    toggle: () => {
      if (state.isActive) api.close();
      else api.openViaButton();
    },

    selectCategory: (category: string) => {
      const idx = Math.max(0, state.categories.indexOf(category));
      setState({
        selectedCategory: category,
        selectedCategoryIndex: idx >= 0 ? idx : 0,
        selectedIndex: 0,
      });
    },

    navigateUp: () => {
      const unlockedCount = getUnlockedCount(
        state.matches,
        state.selectedCategory,
      );
      setState({
        selectedIndex: clampSelection(-1, state.selectedIndex, unlockedCount),
      });
    },

    navigateDown: () => {
      const unlockedCount = getUnlockedCount(
        state.matches,
        state.selectedCategory,
      );
      setState({
        selectedIndex: clampSelection(1, state.selectedIndex, unlockedCount),
      });
    },

    selectMatch: (match: SlashCommandMatch) => {
      const textBefore = state.text.substring(
        0,
        Math.max(0, state.commandStart),
      );
      const textAfter = state.text.substring(
        state.commandEnd >= 0 ? state.commandEnd : state.text.length,
      );
      const newText = textBefore + textAfter;
      const newCursor = Math.max(0, state.commandStart);
      setState({
        text: newText,
        cursorPosition: newCursor,
        isActive: false,
        openedViaButton: false,
      });
      opts.onSelect?.(match, { text: newText, cursor: newCursor });
      return { text: newText, cursor: newCursor };
    },

    selectCurrent: () => {
      const match = getSelectedMatch(
        state.matches,
        state.selectedCategory,
        state.selectedIndex,
      );
      if (!match) return null;
      const result = api.selectMatch(match);
      if (!result) return null;
      return { ...result, match };
    },

    handleKey: (key: SlashKey) => {
      if (!state.isActive) return false;
      const result = handleSlashKey(key, {
        matches: state.matches,
        selectedCategory: state.selectedCategory,
        categories: state.categories,
        selectedIndex: state.selectedIndex,
      });
      switch (result.action) {
        case "navigateUp":
          setState({ selectedIndex: result.nextIndex });
          return true;
        case "navigateDown":
          setState({ selectedIndex: result.nextIndex });
          return true;
        case "nextCategory":
          api.selectCategory(result.nextCategory);
          return true;
        case "select": {
          if (result.match) api.selectMatch(result.match);
          return true;
        }
        case "close":
          api.close();
          return true;
        default:
          return false;
      }
    },

    subscribe: (listener: (s: ComposerState) => void) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },

    constants: COMPOSER_CONSTANTS,
  };

  return api;
}

export const createComposerBase = useComposerBase;

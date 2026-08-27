"use client";

import type React from "react";
import { useCallback, useEffect, useState } from "react";

import {
  type SlashCommandMatch,
  useSlashCommands,
} from "@/features/chat/hooks/useSlashCommands";

export interface SlashCommandDropdownPosition {
  top?: number;
  bottom?: number;
  left: number;
  width: number;
}

interface SlashCommandDropdownState {
  isActive: boolean;
  matches: SlashCommandMatch[];
  selectedIndex: number;
  commandStart: number;
  commandEnd: number;
  dropdownPosition: SlashCommandDropdownPosition;
  openedViaButton: boolean; // Track if dropdown was opened via button
  selectedCategory: string;
  categories: string[];
  selectedCategoryIndex: number;
}

const INITIAL_SLASH_COMMAND_STATE: SlashCommandDropdownState = {
  isActive: false,
  matches: [],
  selectedIndex: 0,
  commandStart: -1,
  commandEnd: -1,
  dropdownPosition: { left: 0, width: 0 },
  openedViaButton: false,
  selectedCategory: "all",
  categories: [],
  selectedCategoryIndex: 0,
};

/** Matches of one category, or all of them for the "all" tab. */
export function filterMatchesByCategory(
  category: string,
  matches: SlashCommandMatch[],
): SlashCommandMatch[] {
  if (category === "all") return matches;
  return matches.filter((match) => match.tool.category === category);
}

/**
 * Compute the dropdown geometry above the composer, matching its width.
 */
function getDropdownPosition(
  textarea: HTMLTextAreaElement | null,
): SlashCommandDropdownPosition | null {
  if (!textarea) return null;

  // Get composer container for proper width
  const composerContainer = textarea.closest(".searchbar");
  const rect =
    composerContainer?.getBoundingClientRect() ||
    textarea.getBoundingClientRect();

  return {
    bottom: rect.top, // Position dropdown bottom at composer top
    left: rect.left,
    width: rect.width, // Match the composer width
  };
}

/**
 * Every tool category (integrations plus non-integration ones like Skills,
 * Notifications, etc.) becomes a top-level tab.
 */
function buildCategories(matches: SlashCommandMatch[]): string[] {
  const uniqueCategories = Array.from(
    new Set(matches.map((match) => match.tool.category)),
  );
  return ["all", ...uniqueCategories.toSorted((a, b) => a.localeCompare(b))];
}

/**
 * Move `selectedIndex` by `delta` within unlocked-row space, clamped to
 * [0, unlockedCount - 1]. All keyboard/pointer navigation must share this
 * single index space — the rendered rows compare their UNLOCKED-list position
 * against selectedIndex, so any full-list arithmetic highlights the wrong row
 * whenever locked items precede an unlocked one.
 */
function clampSelection(
  delta: 1 | -1,
  currentIndex: number,
  unlockedCount: number,
): number {
  if (unlockedCount <= 0) return currentIndex;
  return Math.min(Math.max(currentIndex + delta, 0), unlockedCount - 1);
}

interface UseSlashCommandDropdownStateParams {
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
  searchbarText: string;
  onSearchbarTextChange: (text: string) => void;
  onSlashCommandSelect?: (toolName: string, toolCategory: string) => void;
}

/**
 * The slash-command dropdown state machine for the composer input: detection
 * while typing, selection, category tabs, keyboard navigation, click-outside,
 * and programmatic open/close.
 *
 * NB: keyboard navigation, pointer navigation and Enter/Tab activation all
 * address rows in the same unlocked-only index space (see clampSelection).
 */
export function useSlashCommandDropdownState({
  inputRef,
  searchbarText,
  onSearchbarTextChange,
  onSlashCommandSelect,
}: UseSlashCommandDropdownStateParams) {
  const { detectSlashCommand, getSlashCommandSuggestions } = useSlashCommands();
  const [slashCommandState, setSlashCommandState] = useState(
    INITIAL_SLASH_COMMAND_STATE,
  );

  const closeDropdown = useCallback(() => {
    setSlashCommandState((prev) => ({
      ...prev,
      isActive: false,
      openedViaButton: false,
    }));
  }, []);

  // Open the dropdown programmatically — used by the toolbar button, banner
  // and '/' hotkey via the parent's imperative ref.
  const openOrToggleDropdown = useCallback(() => {
    if (slashCommandState.isActive) {
      // Close the dropdown
      closeDropdown();
      return;
    }

    // Open the dropdown - use getSlashCommandSuggestions with empty query
    // to get all tools with enhancement info (including lock status)
    const allMatches = getSlashCommandSuggestions("");

    // Calculate dropdown position - use same logic as normal slash command detection
    const position = getDropdownPosition(inputRef.current);
    if (!position) return;

    setSlashCommandState({
      isActive: true,
      matches: allMatches,
      selectedIndex: 0,
      commandStart: 0,
      commandEnd: 0,
      dropdownPosition: position,
      openedViaButton: true, // Mark as opened via button
      selectedCategory: "all",
      categories: buildCategories(allMatches),
      selectedCategoryIndex: 0,
    });
  }, [
    closeDropdown,
    getSlashCommandSuggestions,
    inputRef,
    slashCommandState.isActive,
  ]);

  const updateSlashCommandDetection = useCallback(
    (text: string, cursorPosition: number) => {
      const detection = detectSlashCommand(text, cursorPosition);

      if (detection.isSlashCommand && detection.matches.length > 0) {
        // Calculate dropdown position - position above the composer and match its width
        const position = getDropdownPosition(inputRef.current);
        if (!position) return;

        setSlashCommandState({
          isActive: true,
          matches: detection.matches,
          selectedIndex: 0,
          commandStart: detection.commandStart,
          commandEnd: detection.commandEnd,
          dropdownPosition: position,
          openedViaButton: false, // This is a normal slash command detection
          selectedCategory: "all",
          categories: buildCategories(detection.matches),
          selectedCategoryIndex: 0,
        });
      } else {
        // Only close if it wasn't opened via button, or if no matches when opened via button
        setSlashCommandState((prev) => ({
          ...prev,
          isActive: prev.openedViaButton ? prev.isActive : false,
          matches: prev.openedViaButton ? prev.matches : [],
        }));
      }
    },
    [detectSlashCommand, inputRef],
  );

  const handleSlashCommandSelect = useCallback(
    (match: SlashCommandMatch) => {
      // Remove the slash command portion while keeping other text
      const textBeforeCommand = searchbarText.substring(
        0,
        slashCommandState.commandStart,
      );
      const textAfterCommand = searchbarText.substring(
        slashCommandState.commandEnd,
      );
      const newText = textBeforeCommand + textAfterCommand;

      onSearchbarTextChange(newText);
      closeDropdown();

      // Notify parent component about tool selection
      if (onSlashCommandSelect) {
        onSlashCommandSelect(match.tool.name, match.tool.category);
      }

      // Focus back to input and position cursor where the slash command was
      requestAnimationFrame(() => {
        if (inputRef.current) {
          const newCursorPos = slashCommandState.commandStart;
          inputRef.current.setSelectionRange(newCursorPos, newCursorPos);
          inputRef.current.focus();
        }
      });
    },
    [
      searchbarText,
      slashCommandState,
      onSearchbarTextChange,
      onSlashCommandSelect,
      inputRef,
      closeDropdown,
    ],
  );

  // Switch to a category tab and reset the item selection (category tab
  // clicks; the ArrowLeft/ArrowRight keys keep their own bounded variants).
  const selectCategory = useCallback((category: string) => {
    setSlashCommandState((prev) => ({
      ...prev,
      selectedCategory: category,
      selectedCategoryIndex: Math.max(0, prev.categories.indexOf(category)),
      selectedIndex: 0, // Reset to first item when switching categories
    }));
  }, []);

  // Keyboard + pointer navigation share one unlocked-index space (see
  // clampSelection). The old keyboard path scanned the full match list and
  // highlighted the wrong row whenever locked items preceded an unlocked one.
  const navigateUp = useCallback(() => {
    setSlashCommandState((prev) => {
      const filteredMatches = filterMatchesByCategory(
        prev.selectedCategory,
        prev.matches,
      );
      const unlockedCount = filteredMatches.filter(
        (match) => !match.enhancedTool?.isLocked,
      ).length;

      return {
        ...prev,
        selectedIndex: clampSelection(-1, prev.selectedIndex, unlockedCount),
      };
    });
  }, []);

  const navigateDown = useCallback(() => {
    setSlashCommandState((prev) => {
      const filteredMatches = filterMatchesByCategory(
        prev.selectedCategory,
        prev.matches,
      );
      const unlockedCount = filteredMatches.filter(
        (match) => !match.enhancedTool?.isLocked,
      ).length;

      return {
        ...prev,
        selectedIndex: clampSelection(1, prev.selectedIndex, unlockedCount),
      };
    });
  }, []);

  const handleSlashCommandKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (!slashCommandState.isActive) return false;

      const currentFilteredMatches = filterMatchesByCategory(
        slashCommandState.selectedCategory,
        slashCommandState.matches,
      );

      switch (e.key) {
        case "ArrowUp":
          e.preventDefault();
          navigateUp();
          return true;

        case "ArrowDown":
          e.preventDefault();
          setSlashCommandState((prev) => {
            const filteredMatches = filterMatchesByCategory(
              prev.selectedCategory,
              prev.matches,
            );
            const unlockedCount = filteredMatches.filter(
              (match) => !match.enhancedTool?.isLocked,
            ).length;

            return {
              ...prev,
              selectedIndex: clampSelection(
                1,
                prev.selectedIndex,
                unlockedCount,
              ),
            };
          });
          return true;

        case "ArrowLeft":
          e.preventDefault();
          setSlashCommandState((prev) => {
            const newCategoryIndex = Math.max(
              0,
              prev.selectedCategoryIndex - 1,
            );
            const newCategory = prev.categories[newCategoryIndex];
            return {
              ...prev,
              selectedCategory: newCategory,
              selectedCategoryIndex: newCategoryIndex,
              selectedIndex: 0, // Reset to first item when switching categories
            };
          });
          return true;

        case "ArrowRight":
          e.preventDefault();
          setSlashCommandState((prev) => {
            const newCategoryIndex = Math.min(
              prev.categories.length - 1,
              prev.selectedCategoryIndex + 1,
            );
            const newCategory = prev.categories[newCategoryIndex];
            return {
              ...prev,
              selectedCategory: newCategory,
              selectedCategoryIndex: newCategoryIndex,
              selectedIndex: 0, // Reset to first item when switching categories
            };
          });
          return true;

        case "Enter":
        case "Tab": {
          e.preventDefault();
          // selectedIndex lives in unlocked-row space (see clampSelection), so
          // activation must resolve against the unlocked list too — indexing
          // the full list here picked a different row than the one rendered as
          // highlighted whenever a locked match preceded an unlocked one.
          const unlockedFilteredMatches = currentFilteredMatches.filter(
            (match) => !match.enhancedTool?.isLocked,
          );
          const selectedMatch =
            unlockedFilteredMatches[slashCommandState.selectedIndex];
          if (selectedMatch) {
            handleSlashCommandSelect(selectedMatch);
          }
          return true;
        }

        case "Escape":
          e.preventDefault();
          closeDropdown();
          return true;

        default:
          return false;
      }
    },
    [slashCommandState, handleSlashCommandSelect, navigateUp, closeDropdown],
  );

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as Element;

      // Don't close if clicking inside the dropdown or the input
      if (
        target.closest(".slash-command-dropdown") ||
        target.closest(".searchbar") ||
        inputRef.current?.contains(target)
      ) {
        return;
      }

      closeDropdown();
    };

    if (slashCommandState.isActive) {
      document.addEventListener("click", handleClickOutside);
      return () => document.removeEventListener("click", handleClickOutside);
    }
    return undefined;
  }, [slashCommandState.isActive, inputRef, closeDropdown]);

  return {
    slashCommandState,
    openOrToggleDropdown,
    closeDropdown,
    updateSlashCommandDetection,
    handleSlashCommandSelect,
    handleSlashCommandKeyDown,
    navigateUp,
    navigateDown,
    selectCategory,
  };
}

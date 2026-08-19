import { Textarea } from "@heroui/input";
import React, {
  useCallback,
  useEffect,
  useImperativeHandle,
  useState,
} from "react";

import {
  type SlashCommandMatch,
  useSlashCommands,
} from "@/features/chat/hooks/useSlashCommands";

import SlashCommandDropdown from "./SlashCommandDropdown";

interface SearchbarInputProps {
  searchbarText: string;
  onSearchbarTextChange: (text: string) => void;
  handleFormSubmit: (e?: React.FormEvent<HTMLFormElement>) => void;
  handleKeyDown: React.KeyboardEventHandler<HTMLInputElement>;
  currentHeight: number;
  hasMessages: boolean;
  onHeightChange: (height: number) => void;
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
  onSlashCommandSelect?: (toolName: string, toolCategory: string) => void;
  onIntegrationClick?: (integrationId: string) => void;
}

export interface ComposerInputRef {
  toggleSlashCommandDropdown: () => void;
  isSlashCommandDropdownOpen: () => boolean;
}

function getFilteredMatches(
  category: string,
  matches: SlashCommandMatch[],
): SlashCommandMatch[] {
  if (category === "all") return matches;
  return matches.filter((match) => match.tool.category === category);
}

function useSlashCommandController({
  inputRef,
  searchbarText,
  onSearchbarTextChange,
  onSlashCommandSelect,
}: {
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
  searchbarText: string;
  onSearchbarTextChange: (text: string) => void;
  onSlashCommandSelect?: (toolName: string, toolCategory: string) => void;
}) {
  const { detectSlashCommand, getSlashCommandSuggestions } = useSlashCommands();
  const [state, setState] = useState({
    isActive: false,
    matches: [] as SlashCommandMatch[],
    selectedIndex: 0,
    commandStart: -1,
    commandEnd: -1,
    dropdownPosition: { top: 0, left: 0, width: 0 } as {
      top?: number;
      bottom?: number;
      left: number;
      width: number;
    },
    openedViaButton: false,
    selectedCategory: "all",
    categories: [] as string[],
    selectedCategoryIndex: 0,
  });

  const calculateDropdownPosition = useCallback(() => {
    const textarea = inputRef.current;
    if (!textarea) return null;
    const composerContainer = textarea.closest(".searchbar");
    const rect =
      composerContainer?.getBoundingClientRect() ||
      textarea.getBoundingClientRect();
    return {
      bottom: rect.top,
      left: rect.left,
      width: rect.width,
    };
  }, [inputRef]);

  const toggleSlashCommandDropdown = useCallback(() => {
    if (state.isActive) {
      setState((prev) => ({
        ...prev,
        isActive: false,
        openedViaButton: false,
      }));
    } else {
      const allMatches = getSlashCommandSuggestions("");
      const position = calculateDropdownPosition();
      if (!position) return;
      const uniqueCategories = Array.from(
        new Set(allMatches.map((match) => match.tool.category)),
      );
      const categories = ["all", ...uniqueCategories.toSorted()];
      setState({
        isActive: true,
        matches: allMatches,
        selectedIndex: 0,
        commandStart: 0,
        commandEnd: 0,
        dropdownPosition: position,
        openedViaButton: true,
        selectedCategory: "all",
        categories,
        selectedCategoryIndex: 0,
      });
    }
  }, [state.isActive, getSlashCommandSuggestions, calculateDropdownPosition]);

  const updateSlashCommandDetection = useCallback(
    (text: string, cursorPosition: number) => {
      const detection = detectSlashCommand(text, cursorPosition);
      if (detection.isSlashCommand && detection.matches.length > 0) {
        const position = calculateDropdownPosition();
        if (!position) return;
        const uniqueCategories = Array.from(
          new Set(detection.matches.map((match) => match.tool.category)),
        );
        const categories = ["all", ...uniqueCategories.toSorted()];
        setState({
          isActive: true,
          matches: detection.matches,
          selectedIndex: 0,
          commandStart: detection.commandStart,
          commandEnd: detection.commandEnd,
          dropdownPosition: position,
          openedViaButton: false,
          selectedCategory: "all",
          categories,
          selectedCategoryIndex: 0,
        });
      } else {
        setState((prev) => ({
          ...prev,
          isActive: prev.openedViaButton ? prev.isActive : false,
          matches: prev.openedViaButton ? prev.matches : [],
        }));
      }
    },
    [detectSlashCommand, calculateDropdownPosition],
  );

  const handleSlashCommandSelect = useCallback(
    (match: SlashCommandMatch) => {
      const textBeforeCommand = searchbarText.substring(0, state.commandStart);
      const textAfterCommand = searchbarText.substring(state.commandEnd);
      const newText = textBeforeCommand + textAfterCommand;
      onSearchbarTextChange(newText);
      setState((prev) => ({
        ...prev,
        isActive: false,
        openedViaButton: false,
      }));
      if (onSlashCommandSelect) {
        onSlashCommandSelect(match.tool.name, match.tool.category);
      }
      requestAnimationFrame(() => {
        if (inputRef.current) {
          const newCursorPos = state.commandStart;
          inputRef.current.setSelectionRange(newCursorPos, newCursorPos);
          inputRef.current.focus();
        }
      });
    },
    [
      searchbarText,
      state.commandStart,
      state.commandEnd,
      onSearchbarTextChange,
      onSlashCommandSelect,
      inputRef,
    ],
  );

  const handleSlashCommandKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (!state.isActive) return false;
      const currentFilteredMatches = getFilteredMatches(
        state.selectedCategory,
        state.matches,
      );
      switch (e.key) {
        case "ArrowUp":
          e.preventDefault();
          setState((prev) => {
            const filteredMatches = getFilteredMatches(
              prev.selectedCategory,
              prev.matches,
            );
            let newIndex = prev.selectedIndex - 1;
            while (newIndex >= 0) {
              const match = filteredMatches[newIndex];
              if (!match.enhancedTool?.isLocked) break;
              newIndex--;
            }
            return { ...prev, selectedIndex: Math.max(0, newIndex) };
          });
          return true;
        case "ArrowDown":
          e.preventDefault();
          setState((prev) => {
            const filteredMatches = getFilteredMatches(
              prev.selectedCategory,
              prev.matches,
            );
            let newIndex = prev.selectedIndex + 1;
            while (newIndex < filteredMatches.length) {
              const match = filteredMatches[newIndex];
              if (!match.enhancedTool?.isLocked) break;
              newIndex++;
            }
            const lastUnlockedIndex = filteredMatches.findIndex(
              (match, idx) => idx >= newIndex && !match.enhancedTool?.isLocked,
            );
            return {
              ...prev,
              selectedIndex:
                lastUnlockedIndex >= 0 ? lastUnlockedIndex : prev.selectedIndex,
            };
          });
          return true;
        case "ArrowLeft":
          e.preventDefault();
          setState((prev) => {
            const newCategoryIndex = Math.max(
              0,
              prev.selectedCategoryIndex - 1,
            );
            const newCategory = prev.categories[newCategoryIndex];
            return {
              ...prev,
              selectedCategory: newCategory,
              selectedCategoryIndex: newCategoryIndex,
              selectedIndex: 0,
            };
          });
          return true;
        case "ArrowRight":
          e.preventDefault();
          setState((prev) => {
            const newCategoryIndex = Math.min(
              prev.categories.length - 1,
              prev.selectedCategoryIndex + 1,
            );
            const newCategory = prev.categories[newCategoryIndex];
            return {
              ...prev,
              selectedCategory: newCategory,
              selectedCategoryIndex: newCategoryIndex,
              selectedIndex: 0,
            };
          });
          return true;
        case "Enter":
        case "Tab": {
          e.preventDefault();
          const unlockedFilteredMatches = currentFilteredMatches.filter(
            (match) => !match.enhancedTool?.isLocked,
          );
          if (unlockedFilteredMatches.length === 1) {
            handleSlashCommandSelect(unlockedFilteredMatches[0]);
          } else {
            const selectedMatch = currentFilteredMatches[state.selectedIndex];
            if (selectedMatch && !selectedMatch.enhancedTool?.isLocked) {
              handleSlashCommandSelect(selectedMatch);
            }
          }
          return true;
        }
        case "Escape":
          e.preventDefault();
          setState((prev) => ({
            ...prev,
            isActive: false,
            openedViaButton: false,
          }));
          return true;
        default:
          return false;
      }
    },
    [state, handleSlashCommandSelect],
  );

  const closeDropdown = useCallback(() => {
    setState((prev) => ({
      ...prev,
      isActive: false,
      openedViaButton: false,
    }));
  }, []);

  const handleCategoryChange = useCallback((category: string) => {
    setState((prev) => {
      const categoryIndex = prev.categories.indexOf(category);
      return {
        ...prev,
        selectedCategory: category,
        selectedCategoryIndex: categoryIndex,
        selectedIndex: 0,
      };
    });
  }, []);

  const navigateUp = useCallback(() => {
    setState((prev) => {
      const filteredMatches = getFilteredMatches(
        prev.selectedCategory,
        prev.matches,
      );
      let newIndex = prev.selectedIndex - 1;
      while (newIndex >= 0 && newIndex < filteredMatches.length) {
        const match = filteredMatches[newIndex];
        if (!match.enhancedTool?.isLocked) break;
        newIndex--;
      }
      return { ...prev, selectedIndex: Math.max(0, newIndex) };
    });
  }, []);

  const navigateDown = useCallback(() => {
    setState((prev) => {
      const filteredMatches = getFilteredMatches(
        prev.selectedCategory,
        prev.matches,
      );
      const unlockedMatches = filteredMatches.filter(
        (match) => !match.enhancedTool?.isLocked,
      );
      let newIndex = prev.selectedIndex + 1;
      while (newIndex < filteredMatches.length) {
        const match = filteredMatches[newIndex];
        if (!match.enhancedTool?.isLocked) break;
        newIndex++;
      }
      return {
        ...prev,
        selectedIndex: Math.min(unlockedMatches.length - 1, newIndex),
      };
    });
  }, []);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as Element;
      if (
        target.closest(".slash-command-dropdown") ||
        target.closest(".searchbar") ||
        inputRef.current?.contains(target)
      ) {
        return;
      }
      setState((prev) => ({
        ...prev,
        isActive: false,
        openedViaButton: false,
      }));
    };
    if (state.isActive) {
      document.addEventListener("click", handleClickOutside);
      return () => document.removeEventListener("click", handleClickOutside);
    }
    return undefined;
  }, [state.isActive, inputRef]);

  return {
    slashCommandState: state,
    setSlashCommandState: setState,
    toggleSlashCommandDropdown,
    isSlashCommandDropdownOpen: state.isActive,
    updateSlashCommandDetection,
    handleSlashCommandSelect,
    handleSlashCommandKeyDown,
    closeDropdown,
    handleCategoryChange,
    navigateUp,
    navigateDown,
  };
}

const ComposerInput = React.forwardRef<ComposerInputRef, SearchbarInputProps>(
  (
    {
      searchbarText,
      onSearchbarTextChange,
      handleFormSubmit,
      handleKeyDown,
      currentHeight,
      onHeightChange,
      inputRef,
      hasMessages: _hasMessages,
      onSlashCommandSelect,
      onIntegrationClick,
    },
    ref,
  ) => {
    const controller = useSlashCommandController({
      inputRef,
      searchbarText,
      onSearchbarTextChange,
      onSlashCommandSelect,
    });

    useImperativeHandle(
      ref,
      () => ({
        toggleSlashCommandDropdown: controller.toggleSlashCommandDropdown,
        isSlashCommandDropdownOpen: () => controller.isSlashCommandDropdownOpen,
      }),
      [
        controller.toggleSlashCommandDropdown,
        controller.isSlashCommandDropdownOpen,
      ],
    );

    const handleTextChange = useCallback(
      (text: string) => {
        onSearchbarTextChange(text);
        if (inputRef.current) {
          const cursorPosition = inputRef.current.selectionStart || 0;
          controller.updateSlashCommandDetection(text, cursorPosition);
        }
      },
      [onSearchbarTextChange, controller, inputRef],
    );

    const handleKeyDownWithSlashCommands: React.KeyboardEventHandler<HTMLInputElement> =
      useCallback(
        (e) => {
          const wasHandled = controller.handleSlashCommandKeyDown(e);
          if (!wasHandled) {
            handleKeyDown(e);
          }
        },
        [controller, handleKeyDown],
      );

    const handleCursorPositionChange = useCallback(() => {
      requestAnimationFrame(() => {
        if (inputRef.current) {
          const cursorPosition = inputRef.current.selectionStart || 0;
          controller.updateSlashCommandDetection(searchbarText, cursorPosition);
        }
      });
    }, [searchbarText, controller, inputRef]);

    return (
      <>
        <form onSubmit={handleFormSubmit}>
          <Textarea
            ref={inputRef}
            autoFocus
            classNames={{
              inputWrapper:
                " px-3 data-[hover=true]:bg-zinc-800 group-data-[focus-visible=true]:ring-zinc-800 group-data-[focus-visible=true]:ring-offset-0 shadow-none group-data-[focus-visible=true]:ring-transparent",
              innerWrapper: `${currentHeight > 24 ? "items-end" : "items-center"} `,
              input:
                "font-light focus-visible:border-0! focus-visible:border-transparent!",
            }}
            maxRows={13}
            minRows={1}
            placeholder="What can I do for you today? (Type '/' for tools)"
            size="lg"
            value={searchbarText}
            onHeightChange={onHeightChange}
            onKeyDown={handleKeyDownWithSlashCommands}
            onValueChange={handleTextChange}
            onSelect={handleCursorPositionChange}
            onClick={handleCursorPositionChange}
          />
        </form>

        <SlashCommandDropdown
          matches={controller.slashCommandState.matches}
          selectedIndex={controller.slashCommandState.selectedIndex}
          onSelect={controller.handleSlashCommandSelect}
          onClose={controller.closeDropdown}
          position={controller.slashCommandState.dropdownPosition}
          isVisible={controller.slashCommandState.isActive}
          openedViaButton={controller.slashCommandState.openedViaButton}
          selectedCategory={controller.slashCommandState.selectedCategory}
          categories={controller.slashCommandState.categories}
          onCategoryChange={controller.handleCategoryChange}
          onNavigateUp={controller.navigateUp}
          onNavigateDown={controller.navigateDown}
          onIntegrationClick={onIntegrationClick}
        />
      </>
    );
  },
);

ComposerInput.displayName = "ComposerInput";

export default ComposerInput;

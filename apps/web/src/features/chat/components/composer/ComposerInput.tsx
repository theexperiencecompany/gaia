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
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";

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
    const { detectSlashCommand, getSlashCommandSuggestions } =
      useSlashCommands();
    const { integrations } = useIntegrations();

    // Get valid integration IDs (platform + user's custom)
    const validIntegrationIds = React.useMemo(() => {
      return new Set(integrations.map((i) => i.id.toLowerCase()));
    }, [integrations]);
    const [slashCommandState, setSlashCommandState] = useState({
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
      openedViaButton: false, // Track if dropdown was opened via button
      selectedCategory: "all",
      categories: [] as string[],
      selectedCategoryIndex: 0,
    });

    // Expose methods to parent component
    useImperativeHandle(
      ref,
      () => ({
        toggleSlashCommandDropdown: () => {
          if (slashCommandState.isActive) {
            // Close the dropdown
            setSlashCommandState((prev) => ({
              ...prev,
              isActive: false,
              openedViaButton: false,
            }));
          } else {
            // Open the dropdown - use getSlashCommandSuggestions with empty query
            // to get all tools with enhancement info (including lock status)
            const allMatches = getSlashCommandSuggestions("");

            // Calculate dropdown position - use same logic as normal slash command detection
            const textarea = inputRef.current;
            if (textarea) {
              // Get composer container for proper width
              const composerContainer = textarea.closest(".searchbar");
              const rect =
                composerContainer?.getBoundingClientRect() ||
                textarea.getBoundingClientRect();

              const position = {
                bottom: rect.top, // Position dropdown bottom at composer top
                left: rect.left,
                width: rect.width, // Match the composer width
              };

              // Get unique categories from matches, filtered to user's integrations
              const uniqueCategories = Array.from(
                new Set(allMatches.map((match) => match.tool.category)),
              ).filter((cat) => validIntegrationIds.has(cat.toLowerCase()));
              const categories = ["all", ...uniqueCategories.sort()];

              setSlashCommandState({
                isActive: true,
                matches: allMatches,
                selectedIndex: 0,
                commandStart: 0,
                commandEnd: 0,
                dropdownPosition: position,
                openedViaButton: true, // Mark as opened via button
                selectedCategory: "all",
                categories,
                selectedCategoryIndex: 0,
              });
            }
          }
        },
        isSlashCommandDropdownOpen: () => slashCommandState.isActive,
      }),
      [getSlashCommandSuggestions, inputRef, slashCommandState.isActive],
    );

    const updateSlashCommandDetection = useCallback(
      (text: string, cursorPosition: number) => {
        const detection = detectSlashCommand(text, cursorPosition);

        if (detection.isSlashCommand && detection.matches.length > 0) {
          // Calculate dropdown position - position above the composer and match its width
          const textarea = inputRef.current;
          if (textarea) {
            // Get composer container for proper width
            const composerContainer = textarea.closest(".searchbar");
            const rect =
              composerContainer?.getBoundingClientRect() ||
              textarea.getBoundingClientRect();

            // Get unique categories from matches, filtered to user's integrations
            const uniqueCategories = Array.from(
              new Set(detection.matches.map((match) => match.tool.category)),
            ).filter((cat) => validIntegrationIds.has(cat.toLowerCase()));
            const categories = ["all", ...uniqueCategories.sort()];

            setSlashCommandState({
              isActive: true,
              matches: detection.matches,
              selectedIndex: 0,
              commandStart: detection.commandStart,
              commandEnd: detection.commandEnd,
              dropdownPosition: {
                bottom: rect.top, // Position dropdown bottom at composer top
                left: rect.left,
                width: rect.width, // Match the composer width
              },
              openedViaButton: false, // This is a normal slash command detection
              selectedCategory: "all",
              categories,
              selectedCategoryIndex: 0,
            });
          }
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
        setSlashCommandState((prev) => ({
          ...prev,
          isActive: false,
          openedViaButton: false,
        }));

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
      ],
    );

    const handleSlashCommandKeyDown = useCallback(
      (e: React.KeyboardEvent) => {
        if (!slashCommandState.isActive) return false;

        // Get filtered matches based on current category
        const getFilteredMatches = (
          category: string,
          matches: SlashCommandMatch[],
        ) => {
          if (category === "all") return matches;
          return matches.filter((match) => match.tool.category === category);
        };

        const currentFilteredMatches = getFilteredMatches(
          slashCommandState.selectedCategory,
          slashCommandState.matches,
        );

        switch (e.key) {
          case "ArrowUp":
            e.preventDefault();
            setSlashCommandState((prev) => {
              const filteredMatches = getFilteredMatches(
                prev.selectedCategory,
                prev.matches,
              );

              let newIndex = prev.selectedIndex - 1;
              // Skip locked items when navigating up
              while (newIndex >= 0) {
                const match = filteredMatches[newIndex];
                if (!match.enhancedTool?.isLocked) {
                  break;
                }
                newIndex--;
              }

              return {
                ...prev,
                selectedIndex: Math.max(0, newIndex),
              };
            });
            return true;

          case "ArrowDown":
            e.preventDefault();
            setSlashCommandState((prev) => {
              const filteredMatches = getFilteredMatches(
                prev.selectedCategory,
                prev.matches,
              );

              let newIndex = prev.selectedIndex + 1;
              // Skip locked items when navigating down
              while (newIndex < filteredMatches.length) {
                const match = filteredMatches[newIndex];
                if (!match.enhancedTool?.isLocked) {
                  break;
                }
                newIndex++;
              }

              // Find the last unlocked index to properly limit navigation
              const lastUnlockedIndex = filteredMatches.findIndex(
                (match, idx) =>
                  idx >= newIndex && !match.enhancedTool?.isLocked,
              );

              return {
                ...prev,
                selectedIndex:
                  lastUnlockedIndex >= 0
                    ? lastUnlockedIndex
                    : prev.selectedIndex,
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
            // Filter to only unlocked matches
            const unlockedFilteredMatches = currentFilteredMatches.filter(
              (match) => !match.enhancedTool?.isLocked,
            );

            // If there's only one unlocked filtered match, automatically select it
            if (unlockedFilteredMatches.length === 1) {
              handleSlashCommandSelect(unlockedFilteredMatches[0]);
            } else {
              const selectedMatch =
                currentFilteredMatches[slashCommandState.selectedIndex];
              // Only select if the match exists and is not locked
              if (selectedMatch && !selectedMatch.enhancedTool?.isLocked) {
                handleSlashCommandSelect(selectedMatch);
              }
            }
            return true;
          }

          case "Escape":
            e.preventDefault();
            setSlashCommandState((prev) => ({
              ...prev,
              isActive: false,
              openedViaButton: false,
            }));
            return true;

          default:
            return false;
        }
      },
      [slashCommandState, handleSlashCommandSelect],
    );

    const handleTextChange = useCallback(
      (text: string) => {
        onSearchbarTextChange(text);

        // Update slash command detection immediately without setTimeout
        if (inputRef.current) {
          const cursorPosition = inputRef.current.selectionStart || 0;
          updateSlashCommandDetection(text, cursorPosition);
        }
      },
      [onSearchbarTextChange, updateSlashCommandDetection, inputRef],
    );

    const handleKeyDownWithSlashCommands: React.KeyboardEventHandler<HTMLInputElement> =
      useCallback(
        (e) => {
          // First, handle slash command navigation
          const wasHandledBySlashCommand = handleSlashCommandKeyDown(e);

          // If not handled by slash command, pass to original handler
          if (!wasHandledBySlashCommand) {
            handleKeyDown(e);
          }
        },
        [handleSlashCommandKeyDown, handleKeyDown],
      );

    // Update cursor position tracking
    const handleCursorPositionChange = useCallback(() => {
      // Use requestAnimationFrame for better performance
      requestAnimationFrame(() => {
        if (inputRef.current) {
          const cursorPosition = inputRef.current.selectionStart || 0;
          updateSlashCommandDetection(searchbarText, cursorPosition);
        }
      });
    }, [searchbarText, updateSlashCommandDetection, inputRef]);

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

        setSlashCommandState((prev) => ({
          ...prev,
          isActive: false,
          openedViaButton: false,
        }));
      };

      if (slashCommandState.isActive) {
        document.addEventListener("click", handleClickOutside);
        return () => document.removeEventListener("click", handleClickOutside);
      }
    }, [slashCommandState.isActive, inputRef]);

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
            isInvalid={searchbarText.length > 10_000}
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
          matches={slashCommandState.matches}
          selectedIndex={slashCommandState.selectedIndex}
          onSelect={handleSlashCommandSelect}
          onClose={() =>
            setSlashCommandState((prev) => ({
              ...prev,
              isActive: false,
              openedViaButton: false,
            }))
          }
          position={slashCommandState.dropdownPosition}
          isVisible={slashCommandState.isActive}
          openedViaButton={slashCommandState.openedViaButton}
          selectedCategory={slashCommandState.selectedCategory}
          categories={slashCommandState.categories}
          onCategoryChange={(category: string) => {
            const categoryIndex =
              slashCommandState.categories.indexOf(category);
            setSlashCommandState((prev) => ({
              ...prev,
              selectedCategory: category,
              selectedCategoryIndex: categoryIndex,
              selectedIndex: 0, // Reset to first item when switching categories
            }));
          }}
          onNavigateUp={() => {
            setSlashCommandState((prev) => {
              const getFilteredMatches = (
                category: string,
                matches: SlashCommandMatch[],
              ) => {
                if (category === "all") return matches;
                return matches.filter(
                  (match) => match.tool.category === category,
                );
              };
              const filteredMatches = getFilteredMatches(
                prev.selectedCategory,
                prev.matches,
              );
              // Only navigate through unlocked items

              let newIndex = prev.selectedIndex - 1;
              // Keep going up until we find an unlocked item or reach the start
              while (newIndex >= 0 && newIndex < filteredMatches.length) {
                const match = filteredMatches[newIndex];
                if (!match.enhancedTool?.isLocked) {
                  break;
                }
                newIndex--;
              }

              return {
                ...prev,
                selectedIndex: Math.max(0, newIndex),
              };
            });
          }}
          onNavigateDown={() => {
            setSlashCommandState((prev) => {
              const getFilteredMatches = (
                category: string,
                matches: SlashCommandMatch[],
              ) => {
                if (category === "all") return matches;
                return matches.filter(
                  (match) => match.tool.category === category,
                );
              };
              const filteredMatches = getFilteredMatches(
                prev.selectedCategory,
                prev.matches,
              );
              // Only navigate through unlocked items
              const unlockedMatches = filteredMatches.filter(
                (match) => !match.enhancedTool?.isLocked,
              );

              let newIndex = prev.selectedIndex + 1;
              // Keep going down until we find an unlocked item or reach the end
              while (newIndex < filteredMatches.length) {
                const match = filteredMatches[newIndex];
                if (!match.enhancedTool?.isLocked) {
                  break;
                }
                newIndex++;
              }

              return {
                ...prev,
                selectedIndex: Math.min(unlockedMatches.length - 1, newIndex),
              };
            });
          }}
          onIntegrationClick={onIntegrationClick}
        />
      </>
    );
  },
);

ComposerInput.displayName = "ComposerInput";

export default ComposerInput;

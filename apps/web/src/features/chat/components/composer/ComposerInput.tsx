import { Textarea } from "@heroui/input";
import React, { useCallback, useImperativeHandle } from "react";

import { useSlashCommandDropdownState } from "@/features/chat/hooks/useSlashCommandDropdownState";

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
    const {
      slashCommandState,
      openOrToggleDropdown,
      closeDropdown,
      updateSlashCommandDetection,
      handleSlashCommandSelect,
      handleSlashCommandKeyDown,
      navigateUp,
      navigateDown,
      selectCategory,
    } = useSlashCommandDropdownState({
      inputRef,
      searchbarText,
      onSearchbarTextChange,
      onSlashCommandSelect,
    });

    // Expose methods to parent component
    useImperativeHandle(
      ref,
      () => ({
        toggleSlashCommandDropdown: openOrToggleDropdown,
        isSlashCommandDropdownOpen: () => slashCommandState.isActive,
      }),
      [openOrToggleDropdown, slashCommandState.isActive],
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
          matches={slashCommandState.matches}
          selectedIndex={slashCommandState.selectedIndex}
          onSelect={handleSlashCommandSelect}
          onClose={closeDropdown}
          position={slashCommandState.dropdownPosition}
          isVisible={slashCommandState.isActive}
          openedViaButton={slashCommandState.openedViaButton}
          selectedCategory={slashCommandState.selectedCategory}
          categories={slashCommandState.categories}
          onCategoryChange={selectCategory}
          onNavigateUp={navigateUp}
          onNavigateDown={navigateDown}
          onIntegrationClick={onIntegrationClick}
        />
      </>
    );
  },
);

ComposerInput.displayName = "ComposerInput";

export default ComposerInput;

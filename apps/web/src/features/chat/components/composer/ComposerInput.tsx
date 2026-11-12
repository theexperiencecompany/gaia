import { TextArea } from "@heroui/react";
import React, { useCallback, useImperativeHandle } from "react";

import { useAutosizeTextarea } from "@/features/chat/hooks/useAutosizeTextarea";
import { useSlashCommandDropdownState } from "@/features/chat/hooks/useSlashCommandDropdownState";

import SlashCommandDropdown from "./SlashCommandDropdown";

interface SearchbarInputProps {
  searchbarText: string;
  onSearchbarTextChange: (text: string) => void;
  handleFormSubmit: (e?: React.FormEvent<HTMLFormElement>) => void;
  handleKeyDown: React.KeyboardEventHandler<HTMLInputElement>;
  hasMessages: boolean;
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

    useAutosizeTextarea(inputRef, searchbarText);

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
      (e: React.ChangeEvent<HTMLTextAreaElement>) => {
        const text = e.target.value;
        onSearchbarTextChange(text);

        // Update slash command detection immediately without setTimeout
        if (inputRef.current) {
          const cursorPosition = inputRef.current.selectionStart || 0;
          updateSlashCommandDetection(text, cursorPosition);
        }
      },
      [onSearchbarTextChange, updateSlashCommandDetection, inputRef],
    );

    const handleKeyDownWithSlashCommands: React.KeyboardEventHandler<HTMLTextAreaElement> =
      useCallback(
        (e) => {
          // First, handle slash command navigation
          const wasHandledBySlashCommand = handleSlashCommandKeyDown(e);

          // If not handled by slash command, pass to original handler
          if (!wasHandledBySlashCommand) {
            handleKeyDown(
              e as unknown as React.KeyboardEvent<HTMLInputElement>,
            );
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
          <TextArea
            ref={inputRef}
            autoFocus
            className="max-h-84 min-h-12 w-full resize-none rounded-[14px] bg-transparent px-3 py-3 text-base leading-6 font-light shadow-none placeholder:text-foreground-500 focus:ring-0"
            rows={1}
            placeholder="What can I do for you today? (Type '/' for tools)"
            value={searchbarText}
            onKeyDown={handleKeyDownWithSlashCommands}
            onChange={handleTextChange}
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

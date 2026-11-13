import { TextArea } from "@heroui/react";
import React, { useCallback, useImperativeHandle } from "react";

import { inputVariants } from "@/components/shared/controlVariants";
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
        {/* v2's 48px field: one line centres, more lines grow inside an 8px inset */}
        <form
          className="flex min-h-12 items-center"
          onSubmit={handleFormSubmit}
        >
          <TextArea
            ref={inputRef}
            autoFocus
            className={inputVariants({
              variant: "bare",
              placeholder: "muted",
              className:
                "max-h-82 w-full resize-none px-3 py-2 text-base leading-6 font-light shadow-none focus:ring-0",
            })}
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

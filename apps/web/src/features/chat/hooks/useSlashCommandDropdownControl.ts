"use client";

import { useRouter } from "next/navigation";
import type React from "react";
import { useCallback } from "react";
import { useHotkeys } from "react-hotkeys-hook";

import type { SlashCommandDropdownController } from "@/features/chat/hooks/useSlashCommandDropdownState";

interface UseSlashCommandDropdownControlParams {
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
  slashCommand: SlashCommandDropdownController;
}

/**
 * Wires the entry points that open the composer's slash-command dropdown: the
 * '/' hotkey and integration clicks from the banner/dropdown.
 */
export function useSlashCommandDropdownControl({
  inputRef,
  slashCommand,
}: UseSlashCommandDropdownControlParams) {
  const router = useRouter();
  const { openOrToggleDropdown, closeDropdown } = slashCommand;

  const handleToggleSlashCommandDropdown = () => {
    // Focus the input first - this will naturally trigger slash command detection
    if (inputRef.current) {
      inputRef.current.focus();
    }

    openOrToggleDropdown();
  };

  // Handle clicking on an integration in the slash command dropdown
  const handleIntegrationClick = useCallback(
    (integrationId: string) => {
      closeDropdown();
      // Navigate to integrations page with id param
      router.push(`/integrations?id=${encodeURIComponent(integrationId)}`);
    },
    [closeDropdown, router],
  );

  // Global hotkey to trigger slash command dropdown with '/' key
  useHotkeys(
    "slash",
    () => {
      handleToggleSlashCommandDropdown();
    },
    {
      enableOnFormTags: false, // Don't trigger when typing in inputs
      preventDefault: true,
    },
  );

  return { handleToggleSlashCommandDropdown, handleIntegrationClick };
}

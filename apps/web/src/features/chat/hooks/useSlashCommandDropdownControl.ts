"use client";

import { useRouter } from "next/navigation";
import type React from "react";
import { useCallback, useEffect } from "react";
import { useHotkeys } from "react-hotkeys-hook";

import type { ComposerInputRef } from "@/features/chat/components/composer/ComposerInput";

interface UseSlashCommandDropdownControlParams {
  composerInputRef: React.RefObject<ComposerInputRef | null>;
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
  setIsSlashCommandDropdownOpen: (open: boolean) => void;
}

/**
 * Keeps the store's `isSlashCommandDropdownOpen` in sync with the imperative
 * dropdown state owned by ComposerInput, and wires the entry points that open
 * it: the '/' hotkey and integration clicks from the banner/dropdown.
 */
export function useSlashCommandDropdownControl({
  composerInputRef,
  inputRef,
  setIsSlashCommandDropdownOpen,
}: UseSlashCommandDropdownControlParams) {
  const router = useRouter();

  const handleToggleSlashCommandDropdown = () => {
    // Focus the input first - this will naturally trigger slash command detection
    if (inputRef.current) {
      inputRef.current.focus();
    }

    composerInputRef.current?.toggleSlashCommandDropdown();
    // Update the state to reflect the current dropdown state
    setIsSlashCommandDropdownOpen(
      composerInputRef.current?.isSlashCommandDropdownOpen() || false,
    );
  };

  // Handle clicking on an integration in the slash command dropdown
  const handleIntegrationClick = useCallback(
    (integrationId: string) => {
      // Close the dropdown first
      composerInputRef.current?.toggleSlashCommandDropdown();
      setIsSlashCommandDropdownOpen(false);
      // Navigate to integrations page with id param
      router.push(`/integrations?id=${encodeURIComponent(integrationId)}`);
    },
    [composerInputRef, router, setIsSlashCommandDropdownOpen],
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

  // Sync the state with the actual dropdown state
  useEffect(() => {
    const interval = setInterval(() => {
      const isOpen =
        composerInputRef.current?.isSlashCommandDropdownOpen() || false;
      setIsSlashCommandDropdownOpen(isOpen);
    }, 100);

    return () => clearInterval(interval);
  }, [composerInputRef, setIsSlashCommandDropdownOpen]);

  return { handleToggleSlashCommandDropdown, handleIntegrationClick };
}

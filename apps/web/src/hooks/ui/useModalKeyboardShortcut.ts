import { useCallback, useEffect } from "react";
import { usePlatform } from "./usePlatform";

/**
 * Registers a Cmd/Ctrl+Enter keyboard shortcut for modal submit actions.
 * Automatically adds and removes the event listener based on `isOpen`.
 */
export function useModalKeyboardShortcut(
  isOpen: boolean,
  isDisabled: boolean,
  onSubmit: () => void,
): void {
  const { isMac } = usePlatform();

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (!isOpen || isDisabled) return;

      const modifierKey = isMac ? e.metaKey : e.ctrlKey;
      if (modifierKey && e.key === "Enter") {
        e.preventDefault();
        onSubmit();
      }
    },
    [isOpen, isDisabled, isMac, onSubmit],
  );

  useEffect(() => {
    if (isOpen) {
      document.addEventListener("keydown", handleKeyDown);
      return () => document.removeEventListener("keydown", handleKeyDown);
    }
  }, [isOpen, handleKeyDown]);
}

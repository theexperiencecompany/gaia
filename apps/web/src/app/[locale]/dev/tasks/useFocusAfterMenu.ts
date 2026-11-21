import { type RefObject, useEffect } from "react";

/** How long the closing menu takes to hand focus back to its trigger. */
const MENU_FOCUS_RETURN_MS = 80;

/**
 * Focuses a field that a menu choice just opened. The menu's trigger takes focus
 * back as the menu closes, so autoFocus alone loses it; this focuses after that.
 */
export function useFocusAfterMenu(
  field: RefObject<HTMLInputElement | HTMLTextAreaElement | null>,
) {
  useEffect(() => {
    const timer = setTimeout(
      () => field.current?.focus(),
      MENU_FOCUS_RETURN_MS,
    );
    return () => clearTimeout(timer);
  }, [field]);
}

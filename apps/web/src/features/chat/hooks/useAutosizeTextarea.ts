import { type RefObject, useLayoutEffect } from "react";

/**
 * Grow a textarea to fit its content on every value change; CSS max-height caps it and
 * overflow scrolls past that. Replaces v2's react-textarea-autosize in every browser.
 */
export function useAutosizeTextarea(
  ref: RefObject<HTMLTextAreaElement | null>,
  value: string,
): void {
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [ref, value]);
}

// @vitest-environment jsdom
/** Every letter opened in LetterModal has a visible close control, first in tab order. */

import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LetterModal } from "@/components/shared/LetterModal";

describe("letter modal", () => {
  it.each(["sheet", "floating"] as const)(
    "a %s letter closes from its own button",
    (presentation) => {
      const onClose = vi.fn();
      render(
        <LetterModal
          isOpen
          onClose={onClose}
          ariaLabel="Your brief"
          presentation={presentation}
        >
          <a href="/todos">A link inside the letter</a>
        </LetterModal>,
      );

      const dialog = screen.getByRole("dialog");
      const close = within(dialog).getByRole("button", { name: "Close" });
      const tabbable = dialog.querySelectorAll(
        'button:not([tabindex="-1"]), a[href]',
      );
      expect(tabbable[0]).toBe(close);

      fireEvent.click(close);
      expect(onClose).toHaveBeenCalledTimes(1);
    },
  );
});

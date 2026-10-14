// @vitest-environment jsdom
/** One control reveals all three password fields; three identical toggles read as noise to a screen reader. */

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/features/settings/hooks/useSetupStatus", () => ({
  useSetupStatus: () => ({ data: { auth_mode: "local" } }),
}));

import { PasswordChangeSection } from "@/features/settings/components/PasswordChangeSection";

describe("PasswordChangeSection", () => {
  it("has a single show-passwords toggle that reveals every field", () => {
    const { container } = render(<PasswordChangeSection />);

    const toggles = screen.getAllByRole("button", { name: "Show passwords" });
    expect(toggles).toHaveLength(1);

    fireEvent.click(toggles[0]);

    expect(container.querySelectorAll('input[type="password"]')).toHaveLength(
      0,
    );
    expect(container.querySelectorAll('input[type="text"]')).toHaveLength(3);
  });
});

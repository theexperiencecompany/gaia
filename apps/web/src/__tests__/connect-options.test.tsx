// @vitest-environment jsdom
/**
 * The seeded thread's connect row: plain buttons, in-app navigation in the
 * same tab, the integrations page opening the connect flow on arrival.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/features/chat/utils/toolIcons", () => ({
  getToolCategoryIcon: (id: string) => <span data-testid={`icon-${id}`} />,
}));

import ConnectOptions from "@/features/chat/components/bubbles/bot/ConnectOptions";

describe("ConnectOptions", () => {
  it("renders one button per option with the app icon and navigates in the same tab", () => {
    render(
      <ConnectOptions
        connect_options={{
          options: [
            {
              integration_id: "gmail",
              label: "Connect Gmail",
              href: "/integrations?connect=gmail",
            },
            { label: "All integrations", href: "/integrations" },
          ],
        }}
      />,
    );

    expect(screen.getByTestId("icon-gmail")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /connect gmail/i }));
    expect(push).toHaveBeenCalledWith("/integrations?connect=gmail");

    fireEvent.click(screen.getByRole("button", { name: /all integrations/i }));
    expect(push).toHaveBeenCalledWith("/integrations");
  });

  it("renders nothing for an empty row", () => {
    const { container } = render(
      <ConnectOptions connect_options={{ options: [] }} />,
    );
    expect(container.firstChild).toBeNull();
  });
});

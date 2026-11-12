// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { GaiaButton } from "./GaiaButton";
import { LinkButton } from "./LinkButton";

describe("GAIA button variants", () => {
  it("paints default-solid as v2's zinc-700 button, not HeroUI's accent primary", () => {
    render(<GaiaButton variant="default-solid">Save</GaiaButton>);
    const button = screen.getByRole("button", { name: "Save" });
    expect(button.className).toContain("bg-zinc-700");
    expect(button.className).not.toContain("button--primary");
  });

  it("paints accent-soft on the bridged accent tint and still presses", () => {
    const onPress = vi.fn();
    render(
      <GaiaButton variant="accent-soft" onPress={onPress}>
        New chat
      </GaiaButton>,
    );
    const button = screen.getByRole("button", { name: "New chat" });
    expect(button.className).toContain("bg-accent-soft");
    expect(button.className).toContain("text-accent-soft-foreground");
    fireEvent.click(button);
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  it("keeps a caller's class over the variant's", () => {
    render(
      <GaiaButton variant="default-solid" className="bg-zinc-800">
        Cancel
      </GaiaButton>,
    );
    const button = screen.getByRole("button", { name: "Cancel" });
    expect(button.className).toContain("bg-zinc-800");
    expect(button.className).not.toContain("bg-zinc-700");
  });

  it("gives a link the same variants", () => {
    render(
      <LinkButton href="/c" variant="accent-soft">
        Open
      </LinkButton>,
    );
    expect(screen.getByRole("link", { name: "Open" }).className).toContain(
      "bg-accent-soft",
    );
  });
});

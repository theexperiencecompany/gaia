// @vitest-environment jsdom
import { Tooltip } from "@heroui/react";
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

  it("rounds a pill LinkButton instead of leaking shape onto the anchor", () => {
    render(
      <LinkButton href="/c" shape="pill">
        Open
      </LinkButton>,
    );
    const link = screen.getByRole("link", { name: "Open" });
    expect(link.className).toContain("gaia-pill");
    expect(link.hasAttribute("shape")).toBe(false);
  });

  it.each([
    ["muted", "text-zinc-400"],
    ["accent", "text-accent"],
  ] as const)("gives a %s-toned ghost button its text colour", (tone, cls) => {
    render(
      <GaiaButton variant="ghost" tone={tone}>
        Go
      </GaiaButton>,
    );
    expect(screen.getByRole("button", { name: "Go" }).className).toContain(cls);
  });
});

// v3's Tooltip opens only for a child that takes React Aria's trigger props; a
// bare Next.js link never did, so every tooltip around a LinkButton stayed shut.
describe("a tooltip around a link button", () => {
  it("opens on hover", async () => {
    render(
      <Tooltip delay={0} closeDelay={0}>
        <LinkButton href="/c">New Chat</LinkButton>
        <Tooltip.Content>Start a chat</Tooltip.Content>
      </Tooltip>,
    );
    const link = screen.getByRole("link", { name: "New Chat" });
    // React Aria opens a hover tooltip only once a pointer has moved (interaction modality "pointer").
    fireEvent.pointerMove(link, { pointerType: "mouse" });
    fireEvent.pointerEnter(link, { pointerType: "mouse" });
    expect((await screen.findByRole("tooltip")).textContent).toContain(
      "Start a chat",
    );
  });
});

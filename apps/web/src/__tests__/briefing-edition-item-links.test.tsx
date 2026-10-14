// @vitest-environment jsdom
/**
 * Brief items: the owner's copy opens the in-app todo even when the brief also
 * shared a public link; the public copy (no todo_id) opens the shared link.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  BriefingEdition,
  type BriefingEditionPayload,
} from "@/features/briefing/components/BriefingEdition";

const PUBLIC_LINK = "https://heygaia.link/abcdefghijk";

function payload(
  item: BriefingEditionPayload["sections"][number]["items"][number],
): BriefingEditionPayload {
  return {
    kicker: "THE MORNING BRIEF",
    date: "2026-10-14",
    headline: "Your morning",
    lede: "",
    stats: [],
    sections: [{ numeral: "I", title: "GAIA'S WORK", items: [item] }],
    mood: "packed",
    caption: "",
    hue: 10,
  };
}

describe("brief item links", () => {
  it("sends the owner to the in-app todo, not the public page", () => {
    render(
      <BriefingEdition
        payload={payload({
          text: "Deck",
          todo_id: "t1",
          link: PUBLIC_LINK,
          kind: "lookback",
        })}
      />,
    );

    expect(
      screen.getByRole("link", { name: "Deck" }).getAttribute("href"),
    ).toBe("/todos?todoId=t1");
  });

  it("sends a public reader to the link the brief shared", () => {
    render(
      <BriefingEdition
        payload={payload({ text: "Deck", link: PUBLIC_LINK, kind: "lookback" })}
      />,
    );

    expect(
      screen.getByRole("link", { name: "Deck" }).getAttribute("href"),
    ).toBe(PUBLIC_LINK);
  });

  it("renders an unlinked public item as plain text", () => {
    render(
      <BriefingEdition payload={payload({ text: "Deck", kind: "lookback" })} />,
    );

    expect(screen.queryByRole("link")).toBeNull();
  });
});

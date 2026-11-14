// @vitest-environment jsdom
/**
 * The archive thumbnail shows the top of the edition; its crease sits where the
 * letter really folds inside that crop, and is left out when the fold is below it.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BriefCard } from "@/features/briefing/components/BriefCard";

// A 540x1500 edition: a 3:2 crop of its top shows 360 / 1500 = 24% of its height.
const NATURAL_WIDTH = 1620;
const NATURAL_HEIGHT = 4500;

function renderCard(editionFold: number | null) {
  const { container } = render(
    <BriefCard
      brief={{
        headline: "Your morning",
        imageUrl: "https://cdn.example/edition.png",
        editionFold,
      }}
      onPress={() => undefined}
      onWarm={() => undefined}
    />,
  );
  const image = container.querySelector("img");
  if (!image) throw new Error("The preview image did not render");
  fireEvent.load(image);
  return container;
}

describe("brief card crease", () => {
  beforeEach(() => {
    vi.spyOn(HTMLImageElement.prototype, "naturalWidth", "get").mockReturnValue(
      NATURAL_WIDTH,
    );
    vi.spyOn(
      HTMLImageElement.prototype,
      "naturalHeight",
      "get",
    ).mockReturnValue(NATURAL_HEIGHT);
  });

  it("places the crease at the edition's fold inside the crop", async () => {
    const container = renderCard(0.18);

    const crease = await vi.waitFor(() => {
      const found = container.querySelector<HTMLElement>("[data-crease]");
      if (!found) throw new Error("no crease yet");
      return found;
    });
    expect(crease.style.top).toBe("75%");
    expect(screen.getByRole("button", { name: "Open brief: Your morning" }));
  });

  it("leaves the crease out when the fold is below the crop", async () => {
    const container = renderCard(0.5);

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(container.querySelector("[data-crease]")).toBeNull();
  });

  it("leaves the crease out when the edition marks no fold", async () => {
    const container = renderCard(null);

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(container.querySelector("[data-crease]")).toBeNull();
  });
});

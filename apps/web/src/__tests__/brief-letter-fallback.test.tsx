// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("motion/react", () => ({ useInView: () => true }));

const prepareEdition = vi.fn();
vi.mock("@/features/briefing/utils/preparedEdition", () => ({
  holdEdition: (url: string) => ({
    edition: prepareEdition(url),
    release: () => undefined,
  }),
}));

vi.mock("@/features/briefing/components/EditionUnfold", () => ({
  PanelFace: () => null,
}));

import { BriefLetter } from "@/features/briefing/components/BriefLetter";

const HEADLINE = "Three decisions are waiting on you";

function trigger(open: (origin?: DOMRect) => void) {
  return { open, warm: vi.fn(), isBusy: false, isLifted: false };
}

describe("BriefLetter without a usable edition image", () => {
  it("opens the brief from a plain headline button when the brief has no image", () => {
    const onOpen = vi.fn();
    render(
      <BriefLetter
        brief={{ headline: HEADLINE, imageUrl: null, editionFold: 0.3 }}
        trigger={trigger(onOpen)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: HEADLINE }));

    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(prepareEdition).not.toHaveBeenCalled();
  });

  it("falls back to the same button when the image fails to prepare", async () => {
    prepareEdition.mockRejectedValue(new Error("CORS"));
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const onOpen = vi.fn();
    render(
      <BriefLetter
        brief={{
          headline: HEADLINE,
          imageUrl: "https://cdn/edition.png",
          editionFold: 0.3,
        }}
        trigger={trigger(onOpen)}
      />,
    );

    const button = await screen.findByRole("button", { name: HEADLINE });
    fireEvent.click(button);

    await waitFor(() => expect(onOpen).toHaveBeenCalledTimes(1));
  });
});

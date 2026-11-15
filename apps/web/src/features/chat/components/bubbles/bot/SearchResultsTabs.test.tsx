// @vitest-environment jsdom

import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import SearchResultsTabs from "./SearchResultsTabs";

// jsdom never loads images, so the card's preload check resolves every one as loaded.
class LoadingImage {
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  set src(_url: string) {
    queueMicrotask(() => this.onload?.());
  }
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SearchResultsTabs", () => {
  it("shows a result image from a host the app has never configured, as its own URL", async () => {
    vi.stubGlobal("Image", LoadingImage);
    const url = "http://cdn.esawebb.org/archives/images/screen/weic2425a.jpg";

    render(<SearchResultsTabs search_results={{ images: [url] }} />);

    const image = await screen.findByAltText("Search result image 1");
    expect(image.getAttribute("src")).toBe(url);
  });
});

// @vitest-environment jsdom
import type { ImageProps } from "next/image";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { VersusLogos } from "@/components/seo/VersusLogos";

vi.mock("next/image", () => ({
  default: ({ src, alt }: ImageProps) => (
    <span data-src={String(src)} title={alt} />
  ),
}));

const toolLogoSrc = (domain: string): string | null | undefined => {
  const html = renderToStaticMarkup(
    <VersusLogos name="Tool" domain={domain} loading="lazy" />,
  );
  return new DOMParser()
    .parseFromString(html, "text/html")
    .querySelector('[title="Tool"]')
    ?.getAttribute("data-src");
};

describe("VersusLogos", () => {
  it("serves the tools Google's favicon service 404s on from our own icons", () => {
    expect(toolLogoSrc("height.app")).toBe("/images/icons/height.png");
    expect(toolLogoSrc("ticktick.com")).toBe("/images/icons/ticktick.png");
  });

  it("asks Google's favicon service for every other tool", () => {
    expect(toolLogoSrc("notion.so")).toBe(
      "https://www.google.com/s2/favicons?domain=notion.so&sz=128",
    );
  });
});

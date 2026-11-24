// @vitest-environment jsdom
import type { ImageProps } from "next/image";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { Tool } from "@/data/tools";
import ToolCard from "@/features/thanks/components/ToolCard";

vi.mock("next/image", () => ({
  default: ({ src, alt }: ImageProps) => (
    <span data-src={String(src)} title={alt} />
  ),
}));

const sentry: Tool = {
  name: "Sentry",
  url: "https://sentry.io",
  description: "Application monitoring.",
  category: "Monitoring & Analytics",
};

describe("ToolCard", () => {
  it("never loads a favicon from the tool's own site, even when the metadata names one", () => {
    const html = renderToStaticMarkup(
      <ToolCard
        tool={sentry}
        metadata={{
          title: "Sentry",
          description: null,
          favicon: "https://sentry.io/favicon.ico",
          website_name: "Sentry",
          website_image: null,
          url: "https://sentry.io",
        }}
      />,
    );
    const favicon = new DOMParser()
      .parseFromString(html, "text/html")
      .querySelector('[title="Sentry favicon"]')
      ?.getAttribute("data-src");

    expect(favicon).toBe(
      "https://www.google.com/s2/favicons?domain=sentry.io&sz=128",
    );
  });
});

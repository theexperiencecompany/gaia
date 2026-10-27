/**
 * Regression: /best-ai-executive-assistant linked /alternative-to/superhuman,
 * which 308s to /compare/superhuman. The pick links must resolve consolidated pages.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { BestHubPick } from "@/components/seo/BestHubClosing";
import type { BestHubConfig } from "@/components/seo/bestAssistantHubConfig";

const PICK: Pick<
  BestHubConfig,
  | "pickBody"
  | "pickCompareHref"
  | "pickCompareLabel"
  | "pickAlternativeHref"
  | "pickAlternativeLabel"
> = {
  pickBody: "GAIA",
  pickCompareHref: "/compare/sunsama",
  pickCompareLabel: "Compare",
  pickAlternativeHref: "/alternative-to/superhuman",
  pickAlternativeLabel: "Alternative",
};

describe("best hub pick links", () => {
  it("links the final URL of a consolidated page, never its redirect", () => {
    const html = renderToStaticMarkup(
      <BestHubPick config={PICK as BestHubConfig} />,
    );
    const hrefs = [...html.matchAll(/href="([^"]+)"/g)].map((m) => m[1]);
    expect(hrefs).toEqual(["/alternative-to/sunsama", "/compare/superhuman"]);
  });
});

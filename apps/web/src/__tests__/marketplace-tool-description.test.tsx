/** Marketplace tool descriptions arrive from the API as markdown and must reach the page rendered, not as raw syntax. */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ToolCard } from "@/app/[locale]/(landing)/marketplace/[slug]/ToolCard";

function renderDescription(description: string): string {
  return renderToStaticMarkup(
    <ToolCard name="ZOOM_ADD_A_MEETING_REGISTRANT" description={description} />,
  );
}

describe("marketplace tool description", () => {
  it("renders markdown emphasis and inline code as elements", () => {
    const html = renderDescription(
      "Registers a participant. **Prerequisites:** a *licensed* account and `meeting:write` scope.",
    );
    expect(html).not.toContain("**");
    expect(html).not.toContain("`");
    expect(html).toContain("<strong>Prerequisites:</strong>");
    expect(html).toContain("<em>licensed</em>");
    expect(html).toMatch(/<code[^>]*>meeting:write<\/code>/);
  });

  it("shows a markdown link as its label without linking out", () => {
    const html = renderDescription(
      "See [Rate Limit Label](https://marketplace.zoom.us/docs/api-reference/rate-limits).",
    );
    expect(html).toContain("See Rate Limit Label.");
    expect(html).not.toContain("<a");
    expect(html).not.toContain("](");
  });

  it("does not turn a heading into a page heading", () => {
    const html = renderDescription("### PostHog knowledge sources\n\nRun it.");
    expect(html).not.toMatch(/<h\d/);
    expect(html).not.toContain("###");
    expect(html).toContain("PostHog knowledge sources");
  });

  it("keeps cron step syntax literal", () => {
    const html = renderDescription(
      "Schedule with */15 * * * * to run every 15 minutes.",
    );
    expect(html).toContain("*/15 * * * * to run every 15 minutes.");
  });

  it("treats docstring indentation as prose, not a code block", () => {
    const html = renderDescription(
      "Get Airtable context snapshot.\n\n        Zero required parameters.",
    );
    expect(html).not.toContain("<pre");
    expect(html).toContain("Zero required parameters.");
  });
});

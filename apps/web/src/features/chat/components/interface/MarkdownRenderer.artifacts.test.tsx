// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sessionFilesApi } from "@/features/chat/api/sessionFilesApi";
import MarkdownRenderer from "@/features/chat/components/interface/MarkdownRenderer";

const CONVERSATION = "conv-1";

function hrefOf(content: string): string | null | undefined {
  const { container } = render(
    <QueryClientProvider client={new QueryClient()}>
      <MarkdownRenderer content={content} />
    </QueryClientProvider>,
  );
  return container.querySelector("a")?.getAttribute("href");
}

describe("MarkdownRenderer artifact links", () => {
  beforeEach(() => {
    window.history.pushState({}, "", `/c/${CONVERSATION}`);
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        observe = vi.fn();
        unobserve = vi.fn();
        disconnect = vi.fn();
      },
    );
  });

  afterEach(() => {
    window.history.pushState({}, "", "/");
    vi.unstubAllGlobals();
  });

  it.each([
    ["./artifacts/report.pdf", "report.pdf"],
    ["artifacts/out/data.csv", "out/data.csv"],
    ["/workspace/sessions/other/artifacts/chart.png", "chart.png"],
  ])("links %s to the file the conversation serves", (written, path) => {
    expect(hrefOf(`See [the file](${written}).`)).toBe(
      sessionFilesApi.artifactUrl(CONVERSATION, path),
    );
  });

  it("shows an artifact image from the file the conversation serves", () => {
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <MarkdownRenderer content="![chart](./artifacts/chart.png)" />
      </QueryClientProvider>,
    );

    expect(container.querySelector("img")?.getAttribute("src")).toBe(
      sessionFilesApi.artifactUrl(CONVERSATION, "chart.png"),
    );
  });

  it("leaves an ordinary link as written", () => {
    expect(hrefOf("See [docs](https://example.com/artifacts/x).")).toBe(
      "https://example.com/artifacts/x",
    );
  });
});

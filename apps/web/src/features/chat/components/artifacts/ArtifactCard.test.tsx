// @vitest-environment jsdom
/** The chat artifact card tells the user how the artifact ended. */

import type { ArtifactCardData } from "@shared/chat";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const fetchArtifact = vi.fn();

vi.mock("@/features/artifacts/api/artifactsApi", () => ({
  fetchArtifact: (id: string) => fetchArtifact(id),
}));

import { ArtifactCard } from "@/features/chat/components/artifacts/ArtifactCard";

function renderCard(card: ArtifactCardData) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ArtifactCard card={card} />
    </QueryClientProvider>,
  );
}

const base = { stream_id: "s1", kind: "report", title: "Q3 plan" } as const;

describe("ArtifactCard", () => {
  beforeAll(() => {
    // useIsMobile reads the viewport through matchMedia, which jsdom lacks.
    window.matchMedia = (query: string) =>
      ({
        matches: false,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }) as MediaQueryList;
  });

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("says a report cut off at the output limit was too long, and how to get one", () => {
    renderCard({ ...base, status: "failed", reason: "truncated" });

    expect(
      screen.getByText(
        "This report was too long to finish. Ask for a shorter one, or split it into parts.",
      ),
    ).toBeTruthy();
  });

  it("keeps the plain failure for any other reason", () => {
    renderCard({ ...base, status: "failed", reason: "validation" });

    expect(screen.getByText("GAIA couldn't make this report.")).toBeTruthy();
  });
});

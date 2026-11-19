// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/layout/sidebar/RightSidebarSlot", () => ({
  usePanelDrawsClose: () => false,
}));
vi.mock("@/stores/layoutStore", () => ({
  useCloseRightSidebar: () => vi.fn(),
}));
vi.mock("@/features/artifacts/LazyArtifactRenderer", () => ({
  LazyArtifactRenderer: () => null,
}));
vi.mock("@/features/short-links/components/ShareLinkControls", () => ({
  ShareLinkControls: () => null,
}));
vi.mock("@/features/artifacts/api/artifactsApi", () => ({
  fetchArtifact: () => new Promise(() => undefined),
  artifactPdfDownloadUrl: (id: string) =>
    `https://api.test/api/v1/artifacts/${id}/pdf`,
}));

import { ArtifactViewer } from "@/features/chat/components/artifacts/ArtifactViewer";

describe("ArtifactViewer download", () => {
  it("offers the owner a PDF download that uses the owner export, not a public link", () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ArtifactViewer artifactId="a1" title="Q3 plan" />
      </QueryClientProvider>,
    );

    const download = screen.getByLabelText("Download PDF");
    expect(download.getAttribute("href")).toBe(
      "https://api.test/api/v1/artifacts/a1/pdf",
    );
    expect(download.hasAttribute("download")).toBe(true);
  });
});

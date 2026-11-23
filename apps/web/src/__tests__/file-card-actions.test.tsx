// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  createShortLink: vi.fn(),
  fetchShareState: vi.fn(),
  stopSharingShortLink: vi.fn(),
}));
vi.mock("@/features/short-links/api/shortLinksApi", () => api);

import FileArtifactSection from "@/features/chat/components/bubbles/bot/FileArtifactSection";
import { FileCard } from "@/features/chat/components/files/FileCard";

// useIsMobile reads matchMedia, which jsdom lacks.
beforeAll(() => {
  window.matchMedia =
    window.matchMedia ||
    ((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
});

const FILENAME = "q3-board-meeting-notes-final.md";

function renderArtifact() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <FileArtifactSection
        artifact_data={{
          session_id: "conv-1",
          path: FILENAME,
          size_bytes: 2048,
          content_type: "text/markdown",
        }}
      />
    </QueryClientProvider>,
  );
}

describe("a file GAIA made", () => {
  it("puts download and sharing behind one overflow trigger, so the name keeps the width", async () => {
    api.fetchShareState.mockResolvedValue(null);
    renderArtifact();

    const buttons = screen.getAllByRole("button");
    expect(buttons.map((b) => b.getAttribute("aria-label"))).toEqual([
      `Open ${FILENAME}`,
      `Actions for ${FILENAME}`,
    ]);

    fireEvent.click(
      screen.getByRole("button", { name: `Actions for ${FILENAME}` }),
    );
    await screen.findByRole("menuitem", { name: /Download/ });
    expect(screen.getByRole("menuitem", { name: /Copy link/ })).toBeTruthy();
    await waitFor(() => expect(api.fetchShareState).toHaveBeenCalled());
    expect(screen.queryByRole("menuitem", { name: /Stop sharing/ })).toBeNull();
  });
});

describe("an attachment still uploading", () => {
  it("can be removed, which cancels attaching it", () => {
    const onRemove = vi.fn();
    render(<FileCard name="deck.pdf" isUploading onRemove={onRemove} />);

    const remove = screen.getByRole("button", { name: "Remove deck.pdf" });
    expect(remove.hasAttribute("disabled")).toBe(false);
    fireEvent.click(remove);
    expect(onRemove).toHaveBeenCalledOnce();
  });
});

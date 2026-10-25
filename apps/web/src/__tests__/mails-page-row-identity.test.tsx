// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import MailsPage from "@/features/mail/components/MailsPage";
import type { EmailData } from "@/types/features/mailTypes";

/**
 * Regression test: MailsPage defined its react-window row component inside
 * the page, so every page re-render (a selection toggle, a read-status change)
 * handed react-window a new component type and every visible row remounted —
 * the focused checkbox was detached and keyboard focus fell to <body>.
 */

const email = (id: string, subject: string): EmailData => ({
  id,
  from: `${id}@example.com`,
  subject,
  time: new Date().toISOString(),
  labelIds: ["INBOX"],
  payload: {
    parts: [],
    body: { size: 0 },
    payload: { headers: [] },
  },
});

const EMAILS = [email("m1", "First"), email("m2", "Second")];

vi.mock("next/dynamic", () => ({ default: () => () => null }));
vi.mock("@/hooks/ui/useMediaQuery", () => ({ default: () => false }));
vi.mock("@/features/mail/api/mailApi", () => ({ mailApi: {} }));
vi.mock("@/features/mail/hooks/useEmailReadStatus", () => ({
  useEmailReadStatus: () => ({ toggleReadStatus: vi.fn() }),
}));
vi.mock("@/features/mail/hooks/useEmailActions", () => ({
  useEmailActions: () => ({
    toggleStarStatus: vi.fn(),
    archiveEmail: vi.fn(),
    trashEmail: vi.fn(),
  }),
}));
vi.mock("@/features/mail/hooks/useEmailAnalysis", () => ({
  useEmailAnalysisIndicators: () => ({ hasAnalysis: () => false }),
}));
vi.mock("@/features/mail/hooks/useEmailViewer", () => ({
  useEmailViewer: () => ({
    threadMessages: [],
    isLoadingThread: false,
    openEmail: vi.fn(),
    closeEmail: vi.fn(),
    selectedEmailId: null,
  }),
}));
vi.mock("@/features/mail/hooks/useInfiniteEmails", () => ({
  useInfiniteEmails: () => ({
    emails: EMAILS,
    isLoading: false,
    isItemLoaded: (index: number, total: number) => index < total,
    loadMoreItems: vi.fn(),
    error: null,
  }),
}));

describe("MailsPage row identity", () => {
  it("keeps a row mounted, and its focus, when the selection changes", () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MailsPage />
      </QueryClientProvider>,
    );

    const [checkbox] = screen.getAllByRole("button", { name: "Select email" });
    checkbox.focus();
    fireEvent.click(checkbox);

    expect(screen.getByRole("button", { name: "Deselect email" })).toBe(
      checkbox,
    );
    expect(document.activeElement).toBe(checkbox);
  });
});

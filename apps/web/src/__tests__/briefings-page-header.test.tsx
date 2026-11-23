// @vitest-environment jsdom
/** The Briefings page names itself in the app's top header bar, like every other main page. */

import { render, screen } from "@testing-library/react";
import { isValidElement, type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

const setHeader = vi.fn<(header: ReactNode) => void>();
vi.mock("@/hooks/layout/useHeader", () => ({
  useHeader: () => ({ header: null, setHeader }),
}));

vi.mock("@/features/briefing/components/BriefingArchive", () => ({
  BriefingArchive: () => null,
}));

import BriefingsPage from "@/app/[locale]/(main)/briefings/page";
import BriefingsHeader from "@/components/layout/headers/BriefingsHeader";

describe("briefings page", () => {
  it("registers its header and drops the in-page title", () => {
    render(<BriefingsPage />);

    const registered = setHeader.mock.calls[0]?.[0];
    expect(isValidElement(registered) && registered.type).toBe(BriefingsHeader);
    expect(screen.queryByRole("heading", { name: "Briefings" })).toBeNull();
  });
});

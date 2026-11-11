// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { renderToString } from "react-dom/server";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

vi.mock("@/features/auth/hooks/useAuth", () => ({
  useAuth: () => ({ isAuthenticated: false }),
}));
vi.mock("@/features/chat/components/interface/RichContentRenderer", () => ({
  RichContentRenderer: ({ content }: { content: string }) => <p>{content}</p>,
}));

import { LinkUnavailable } from "@/features/short-links/components/LinkUnavailable";
import { PublicWorkflowRunView } from "@/features/short-links/components/PublicWorkflowRunView";
import type { PublicWorkflowRun } from "@/types/features/shortLinkTypes";

const RUN: PublicWorkflowRun = {
  target_type: "workflow_run",
  workflow_title: "Morning digest",
  status: "success",
  started_at: "2026-11-10T06:27:00Z",
  completed_at: "2026-11-10T06:28:00Z",
  summary: "Done",
};

function withLocale(children: ReactNode) {
  return (
    <NextIntlClientProvider locale="en" messages={{}}>
      {children}
    </NextIntlClientProvider>
  );
}

describe("a stopped heygaia.link", () => {
  it("says the link is off and leads to GAIA, not the site 404", () => {
    render(<LinkUnavailable />);

    expect(
      screen.getByRole("heading", { name: "This link isn't available" }),
    ).toBeTruthy();
    expect(
      screen.getByText("The person who shared it may have turned it off."),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Go to GAIA" }).getAttribute("href"),
    ).toBe("/");
  });
});

describe("a shared workflow run", () => {
  const originalTz = process.env.TZ;
  beforeAll(() => {
    process.env.TZ = "Asia/Kolkata";
  });
  afterAll(() => {
    process.env.TZ = originalTz;
  });

  it("shows when it ran in the reader's own time zone", () => {
    render(withLocale(<PublicWorkflowRunView view={RUN} />));

    const time = document.querySelector("time");
    expect(time?.textContent).toContain("11:57");
    expect(time?.textContent).not.toContain("UTC");
  });

  it("server-renders the run's date, with no clock time to disagree with the reader's", () => {
    const html = renderToString(
      withLocale(<PublicWorkflowRunView view={RUN} />),
    );

    expect(html).toMatch(
      /<time dateTime="2026-11-10T06:27:00Z"[^>]*>Nov 10, 2026<\/time>/,
    );
  });
});

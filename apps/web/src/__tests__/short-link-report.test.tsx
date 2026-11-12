// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const post = vi.hoisted(() => vi.fn(() => Promise.resolve(undefined)));
vi.mock("@/lib/api/typed", () => ({ api: { post } }));

import { ReportLinkButton } from "@/features/short-links/components/ReportLinkButton";

describe("ReportLinkButton", () => {
  it("reports the link for the chosen reason and closes", async () => {
    render(<ReportLinkButton slug="abcdefghijk" label="file" />);

    fireEvent.click(screen.getByRole("button", { name: "Report" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("Report this file");
    for (const reason of [
      "Phishing or a scam",
      "Malware or a harmful download",
      "Harassment or hate",
      "Illegal content",
      "Something else",
    ]) {
      expect(screen.getByLabelText(reason)).toBeTruthy();
    }

    const send = screen.getByRole("button", { name: "Send report" });
    expect(send.hasAttribute("disabled")).toBe(true);
    fireEvent.click(screen.getByLabelText("Phishing or a scam"));
    fireEvent.click(send);

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/l/{slug}/report", {
        path: { slug: "abcdefghijk" },
        body: { reason: "phishing", turnstile_token: null },
        successMessage: "Thanks. We'll review this link.",
        errorMessage: "Couldn't send the report",
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});

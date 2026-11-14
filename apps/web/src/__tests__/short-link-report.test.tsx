// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { forwardRef, useImperativeHandle } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const post = vi.hoisted(() => vi.fn(() => Promise.resolve(undefined)));
vi.mock("@/lib/api/typed", () => ({ api: { post } }));

// The site key is pinned per test: CI's web lane sets NEXT_PUBLIC_TURNSTILE_SITE_KEY for its build.
const turnstile = vi.hoisted(() => ({
  siteKey: undefined as string | undefined,
}));
vi.mock("@/features/contact/constants", () => ({
  get TURNSTILE_SITE_KEY() {
    return turnstile.siteKey;
  },
}));
vi.mock("@marsidev/react-turnstile", () => ({
  Turnstile: forwardRef(function FakeTurnstile(_props, ref) {
    useImperativeHandle(ref, () => ({
      getResponsePromise: () => Promise.resolve("turnstile-token"),
      reset: () => undefined,
    }));
    return null;
  }),
}));

import { ReportLinkButton } from "@/features/short-links/components/ReportLinkButton";

async function reportPhishing() {
  render(<ReportLinkButton slug="abcdefghijk" label="file" />);
  fireEvent.click(screen.getByRole("button", { name: "Report" }));
  await screen.findByRole("dialog");
  fireEvent.click(screen.getByLabelText("Phishing or a scam"));
  fireEvent.click(screen.getByRole("button", { name: "Send report" }));
}

function expectReported(turnstileToken: string | null) {
  expect(post).toHaveBeenCalledWith("/api/v1/l/{slug}/report", {
    path: { slug: "abcdefghijk" },
    body: { reason: "phishing", turnstile_token: turnstileToken },
    successMessage: "Thanks. We'll review this link.",
    errorMessage: "Couldn't send the report",
  });
}

describe("ReportLinkButton", () => {
  beforeEach(() => {
    post.mockClear();
    turnstile.siteKey = undefined;
  });

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

    await waitFor(() => expectReported(null));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("sends the Turnstile token where the deployment checks one", async () => {
    turnstile.siteKey = "0x4AAAAAAA-test";

    await reportPhishing();

    await waitFor(() => expectReported("turnstile-token"));
  });
});

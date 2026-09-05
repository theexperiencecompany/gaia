// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import EmailComposeCard from "@/features/mail/components/EmailComposeCard";

/**
 * Regression test: a compose card carrying a `draft_id` sends that stored draft
 * verbatim (`sendDraft`), so any edit the user makes to subject, body or
 * recipients is discarded. It used to render the pencil buttons and recipient
 * pickers anyway — the user edited, saved ("Email updated successfully!"), hit
 * Send, and the original draft went out. A locked card offers no edit
 * affordances; remove the isLocked guards and this fails.
 */

vi.mock("@/features/mail/api/mailApi", () => ({
  mailApi: { sendDraft: vi.fn(), sendEmail: vi.fn() },
}));

const BASE = {
  to: ["bob@example.com"],
  subject: "Quarterly report",
  body: "<p>Attached.</p>",
};

describe("EmailComposeCard draft lock", () => {
  it("offers no edit affordances when the card sends a stored draft", () => {
    render(
      <EmailComposeCard
        emailData={{
          ...BASE,
          draft_id: "d-1",
          attachments: [{ name: "q3.pdf", mimetype: "application/pdf" }],
        }}
      />,
    );

    expect(screen.getByText("q3.pdf")).toBeDefined();
    // Collapse toggle and Send, and nothing else: no subject/body pencils, no
    // recipient pickers. Counting is what keeps this honest — the pencils are
    // icon-only and have no name to query by.
    expect(screen.getAllByRole("button")).toHaveLength(2);
    expect(screen.getByRole("button", { name: /send draft/i })).toBeDefined();
    expect(screen.queryByRole("button", { name: /add cc/i })).toBeNull();
  });

  it("keeps the card editable when there is no draft to send", () => {
    render(<EmailComposeCard emailData={BASE} />);

    expect(screen.getByRole("button", { name: /add cc/i })).toBeDefined();
  });

  it("shows every recipient of a stored draft instead of asking the user to pick", () => {
    // A proposed compose may list candidates for the user to choose between; a
    // draft's recipients are already settled, and dropping them left Send
    // permanently disabled on any draft addressed to more than one person.
    render(
      <EmailComposeCard
        emailData={{
          ...BASE,
          to: ["bob@example.com", "carol@example.com"],
          draft_id: "d-2",
        }}
      />,
    );

    expect(
      screen.getByText("bob@example.com, carol@example.com"),
    ).toBeDefined();
    expect(
      screen
        .getByRole("button", { name: /send draft/i })
        .getAttribute("disabled"),
    ).toBeNull();
  });
});

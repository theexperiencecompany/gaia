// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import GmailBody from "@/features/mail/components/GmailBody";
import type { EmailData } from "@/types/features/mailTypes";

/**
 * Regression test: email bodies are third-party HTML, and the sanitizer used to
 * whitelist <iframe>, so a received email could frame any page inside the app.
 */

function emailWithHtml(html: string): EmailData {
  return {
    id: "m-1",
    from: "sender@example.com",
    subject: "Hi",
    time: "2026-01-01T00:00:00Z",
    payload: {
      parts: [
        {
          mimeType: "text/html",
          body: { size: html.length, data: btoa(html) },
        },
      ],
      body: { size: 0 },
      payload: { headers: [] },
    },
  };
}

describe("GmailBody sanitization", () => {
  it("drops iframes from a received email while keeping its content", () => {
    const { container } = render(
      <GmailBody
        email={emailWithHtml(
          '<p>Hello</p><iframe src="https://attacker.example/login"></iframe>',
        )}
      />,
    );

    const shadowRoot = container.querySelector(".bg-white")?.shadowRoot;
    expect(shadowRoot?.textContent).toContain("Hello");
    expect(shadowRoot?.querySelector("iframe")).toBeNull();
  });
});

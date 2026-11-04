// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import { sanitizeEmailHtml } from "@/features/mail/utils/sanitizeEmailHtml";

/** Regression: the sanitizer used to whitelist <iframe>, so a received email could frame any page inside the app. */
describe("sanitizeEmailHtml", () => {
  it("drops iframes from a received email while keeping its content", () => {
    const container = document.createElement("div");
    container.innerHTML = sanitizeEmailHtml(
      '<p>Hello</p><iframe src="https://attacker.example/login"></iframe>',
    );

    expect(container.textContent).toContain("Hello");
    expect(container.querySelector("iframe")).toBeNull();
  });
});

import { describe, expect, it } from "vitest";

import { describeTodoRunWake } from "./runWake";

const wake = {
  trigger_names: [],
  approval_summary: null,
};

describe("describeTodoRunWake", () => {
  it("names a scheduled run", () => {
    expect(describeTodoRunWake({ ...wake, kind: "schedule" })).toBe(
      "Scheduled run",
    );
  });

  it("names the events that woke it in words, not trigger ids", () => {
    expect(
      describeTodoRunWake({
        ...wake,
        kind: "trigger",
        trigger_names: ["gmail_email_sent", "gmail_new_message"],
      }),
    ).toBe("Woke up on sent emails and on new emails");
  });

  it("falls back to the trigger id it has no words for", () => {
    expect(
      describeTodoRunWake({
        ...wake,
        kind: "trigger",
        trigger_names: ["acme_widget_moved"],
      }),
    ).toBe("Woke up on acme_widget_moved");
  });

  it("quotes what the user approved", () => {
    expect(
      describeTodoRunWake({
        ...wake,
        kind: "approval",
        approval_summary: "send the reply",
      }),
    ).toBe("You approved: send the reply");
  });

  it("still says the user approved when there is no summary", () => {
    expect(describeTodoRunWake({ ...wake, kind: "approval" })).toBe(
      "You approved it",
    );
  });
});

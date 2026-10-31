import { describe, expect, it } from "vitest";

import { describeTodoRunWake } from "./runWake";

const wake = {
  todo_id: "t1",
  todo_title: "Watch the deploy",
  trigger_names: [],
  approval_summary: null,
};

describe("describeTodoRunWake", () => {
  it("names a scheduled run", () => {
    expect(describeTodoRunWake({ ...wake, kind: "schedule" })).toBe(
      "Scheduled run",
    );
  });

  it("names every event that woke a triggered run", () => {
    expect(
      describeTodoRunWake({
        ...wake,
        kind: "trigger",
        trigger_names: ["gmail_new_message", "github_pr_opened"],
      }),
    ).toBe("Woke up on gmail_new_message and on github_pr_opened");
  });

  it("words the events with the label the app passes", () => {
    expect(
      describeTodoRunWake(
        { ...wake, kind: "trigger", trigger_names: ["gmail_new_message"] },
        () => "on new emails",
      ),
    ).toBe("Woke up on new emails");
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

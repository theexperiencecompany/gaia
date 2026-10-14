/**
 * A browser card asks the user to act only while its run is alive. The run's
 * terminal result settles any handoff it never sent a resolved snapshot for
 * (a run that failed mid-handoff), or the prompt would sit under "Didn't finish".
 */

import { describe, expect, it } from "vitest";
import { foldBrowserTask } from "@/features/browser/utils";
import type { BrowserTaskSnapshot } from "@/types/features/browserTaskTypes";

const asked: BrowserTaskSnapshot[] = [
  {
    kind: "session",
    task: "Book a table",
    status: "running",
    session_id: "s1",
  },
  {
    kind: "handoff",
    handoff_id: "h1",
    reason: "Sign in to continue",
    status: "pending",
  },
];

describe("foldBrowserTask", () => {
  it("asks the user to act while the run waits on them", () => {
    expect(foldBrowserTask(asked).pendingHandoff?.handoff_id).toBe("h1");
  });

  it("asks nothing once the run has ended, resolved snapshot or not", () => {
    const ended = foldBrowserTask([
      ...asked,
      {
        kind: "result",
        status: "failed",
        success: false,
        summary: "The browser was lost.",
      },
    ]);

    expect(ended.result?.status).toBe("failed");
    expect(ended.pendingHandoff).toBeUndefined();
  });
});
